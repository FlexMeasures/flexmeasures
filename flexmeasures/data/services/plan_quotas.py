"""Enforce organisation plan quotas for all ORM creation paths."""

from collections import defaultdict

from sqlalchemy import event, func, inspect, select
from sqlalchemy.orm import Session

from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.user import Account, Plan, User

QUOTAS = (
    ("users", User, "account_id", "max_users"),
    ("assets", GenericAsset, "account_id", "max_assets"),
    ("client organisations", Account, "consultancy_account_id", "max_clients"),
)


class PlanQuotaExceeded(Exception):
    """An organisation's plan prevents an operation."""


def _target_id(obj, field: str) -> int | None:
    """Resolve a target even when an ORM relationship set its foreign key later."""
    relationship = _relationship_for(obj, field)
    relationship_history = inspect(obj).attrs[relationship].history
    if relationship_history.has_changes():
        related = getattr(obj, relationship)
        return related.id if related is not None else None
    value = getattr(obj, field)
    if value is not None:
        return value
    related = getattr(obj, relationship, None)
    return related.id if related is not None else None


def _relationship_for(obj, field: str) -> str:
    return {
        "account_id": "account" if isinstance(obj, User) else "owner",
        "consultancy_account_id": "consultancy_account",
    }[field]


def _old_target_id(obj, field: str) -> int | None:
    """Find the organisation an existing row is leaving."""
    relationship_history = inspect(obj).attrs[_relationship_for(obj, field)].history
    if relationship_history.has_changes() and relationship_history.deleted:
        return relationship_history.deleted[0].id
    foreign_key_history = inspect(obj).attrs[field].history
    return foreign_key_history.deleted[0] if foreign_key_history.deleted else None


def _enforce_consultancy_roles(session: Session) -> None:
    """A plan with no clients cannot acquire consultancy privileges."""
    for obj in session.new.union(session.dirty):
        if isinstance(obj, Account):
            role_history = inspect(obj).attrs.account_roles.history
            if not role_history.added:
                continue
            roles = role_history.added
            forbidden_role = "Consultancy"
        elif isinstance(obj, User):
            role_history = inspect(obj).attrs.flexmeasures_roles.history
            moved = (
                inspect(obj).attrs.account.history.has_changes()
                or inspect(obj).attrs.account_id.history.has_changes()
            )
            if not role_history.added and not moved:
                continue
            roles = obj.flexmeasures_roles if moved else role_history.added
            forbidden_role = "consultant"
        else:
            continue
        if not any(role.name == forbidden_role for role in roles):
            continue
        if isinstance(obj, Account):
            plan = _plan_for(obj, session)
        else:
            account_id = _target_id(obj, "account_id")
            account = (
                session.get(Account, account_id)
                if account_id is not None
                else obj.account
            )
            plan = _plan_for(account, session) if account is not None else None
        if plan is not None and plan.max_clients == 0:
            raise PlanQuotaExceeded(
                "This organisation's plan does not allow consultancy privileges."
            )


def _plan_for(account: Account, session: Session) -> Plan | None:
    """Also resolve a plan ID on an account awaiting its first flush."""
    if inspect(account).attrs.plan.history.has_changes():
        return account.plan
    return session.get(Plan, account.plan_id) if account.plan_id is not None else None


def _new_owner(obj) -> Account | None:
    if isinstance(obj, Account):
        return obj.consultancy_account
    return obj.account if isinstance(obj, User) else obj.owner


def _count_new(session, label, model, field, additions, new_account_additions):
    for obj in session.new:
        if not isinstance(obj, model):
            continue
        if (target := _target_id(obj, field)) is not None:
            additions[(target, label)] += 1
        elif (owner := _new_owner(obj)) is not None and owner in session.new:
            new_account_additions[(owner, label)] += 1


def _count_dirty(session, label, model, field, additions, removals):
    for obj in session.dirty:
        if not isinstance(obj, model) or obj in session.deleted:
            continue
        history = inspect(obj).attrs[field].history
        relationship_history = inspect(obj).attrs[_relationship_for(obj, field)].history
        if not history.has_changes() and not relationship_history.has_changes():
            continue
        target = _target_id(obj, field)
        old_target = _old_target_id(obj, field)
        if target == old_target:
            continue
        if target is not None:
            additions[(target, label)] += 1
        if old_target is not None:
            removals[(old_target, label)] += 1


def _pending_changes(session: Session):
    """Count rows entering and leaving each organisation in this flush."""
    additions: dict[tuple[int, str], int] = defaultdict(int)
    removals: dict[tuple[int, str], int] = defaultdict(int)
    new_account_additions: dict[tuple[Account, str], int] = defaultdict(int)
    for label, model, field, _ in QUOTAS:
        _count_new(session, label, model, field, additions, new_account_additions)
        for obj in session.deleted:
            if (
                isinstance(obj, model)
                and (target := _target_id(obj, field)) is not None
            ):
                removals[(target, label)] += 1
        _count_dirty(session, label, model, field, additions, removals)
    return additions, removals, new_account_additions


def _enforce_new_account_quotas(session: Session, new_account_additions) -> None:
    """Check new organisations before they have an ID to lock or count in SQL."""
    for (account, label), added in new_account_additions.items():
        plan = _plan_for(account, session)
        limit_field = next(field for name, _, _, field in QUOTAS if name == label)
        limit = getattr(plan, limit_field) if plan is not None else None
        if limit is not None and added > limit:
            raise PlanQuotaExceeded(
                f"This organisation's plan allows at most {limit} {label}. "
                "It currently has 0."
            )


def _enforce_existing_account_quotas(session: Session, additions, removals) -> None:
    """Serialize additions per account, then count persisted and pending rows."""
    account_ids = sorted({account_id for account_id, _ in additions})
    locked_plan_ids = dict(
        session.execute(
            select(Account.id, Account.plan_id)
            .where(Account.id.in_(account_ids))
            .order_by(Account.id)
            .with_for_update()
        ).all()
    )
    for label, model, field, limit_field in QUOTAS:
        for account_id in account_ids:
            added = additions[(account_id, label)]
            if not added or account_id not in locked_plan_ids:
                continue
            account = session.get(Account, account_id)
            assert account is not None
            plan_changed = (
                inspect(account).attrs.plan.history.has_changes()
                or inspect(account).attrs.plan_id.history.has_changes()
            )
            plan = (
                _plan_for(account, session)
                if plan_changed
                else (
                    session.get(Plan, locked_plan_ids[account_id])
                    if locked_plan_ids[account_id] is not None
                    else None
                )
            )
            limit = getattr(plan, limit_field) if plan is not None else None
            if limit is None:
                continue
            current = (
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(getattr(model, field) == account_id)
                )
                or 0
            )
            if current + added - removals[(account_id, label)] > limit:
                resource = label.removesuffix("s") if limit == 1 else label
                raise PlanQuotaExceeded(
                    f"This organisation's plan allows at most {limit} {resource}. "
                    f"It currently has {current}."
                )


@event.listens_for(Session, "before_flush")
def enforce_plan_quotas(session: Session, flush_context, instances) -> None:
    """Apply plan constraints across ORM paths, including recursive asset copies."""
    _enforce_consultancy_roles(session)
    additions, removals, new_account_additions = _pending_changes(session)
    if new_account_additions:
        _enforce_new_account_quotas(session, new_account_additions)
    if additions:
        _enforce_existing_account_quotas(session, additions, removals)
