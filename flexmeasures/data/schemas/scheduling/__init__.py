from __future__ import annotations

from collections import OrderedDict
from datetime import timedelta
from typing import Any, Callable, Dict

from flask import current_app

from marshmallow import (
    Schema,
    fields,
    validate,
    validates,
    validates_schema,
    ValidationError,
    pre_load,
    post_dump,
    post_load,
)

from flexmeasures import Sensor

from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.sensors import (
    VariableQuantityField,
    SensorIdField,
    SensorReference,
    OutputSensorReferenceSchema,
)
from flexmeasures.data.schemas.scheduling import metadata
from flexmeasures.data.schemas.units import UnitField
from flexmeasures.utils.doc_utils import rst_to_openapi
from flexmeasures.data.schemas.times import (
    AwareDateTimeField,
    DurationField,
    PlanningDurationField,
)
from flexmeasures.data.schemas.utils import FMValidationError
from flexmeasures.utils.flexmeasures_inflection import p
from flexmeasures.utils.unit_utils import (
    ur,
    units_are_convertible,
    is_capacity_price_unit,
    is_energy_price_unit,
    is_power_unit,
    is_currency_unit,
    is_energy_unit,
)
from flexmeasures.utils.validation_utils import validate_variable_quantity


class NoTimeSeriesSpecs(Schema):

    @validates_schema
    def forbid_time_series_specs(self, data: dict, **kwargs):
        """Do not allow time series specs for the flex-context fields saved in the db."""

        # List of keys to check for time series specs
        keys_to_check = []
        # All the keys in this list are all fields of type VariableQuantity
        for field_var, field in self.declared_fields.items():
            if isinstance(field, VariableQuantityField):
                keys_to_check.append((field_var, field))

        # Check each key and raise a ValidationError if it's a list
        for field_var, field in keys_to_check:
            if field_var in data and isinstance(data[field_var], list):
                raise ValidationError(
                    "A time series specification (listing segments) is not supported when storing flex-context fields. Use a fixed quantity or a sensor reference instead.",
                    field_name=field.data_key,
                )


class CommitmentSchema(Schema):
    name = fields.Str(required=True, data_key="name")
    # Undocumented for now (not part of UI_FLEX_CONTEXT_SCHEMA, OpenAPI or Sphinx docs).
    # Internal bookkeeping only: not the documented way to associate a commitment
    # with a commodity. API users should instead place the commitment under the
    # relevant entry of the multi-commodity `commodities` list (one flex-context
    # per commodity) -- see StorageScheduler.convert_to_commitments, which matches
    # this field against each device's own `commodity`, defaulting to
    # "electricity" as well.
    commodity = fields.Str(
        required=False,
        load_default="electricity",
        data_key="commodity",
    )
    baseline = VariableQuantityField("MW", required=False, data_key="baseline")
    up_price = VariableQuantityField("/MW", required=False, data_key="up-price")
    down_price = VariableQuantityField(
        "/MW",
        required=False,
        data_key="down-price",
    )

    @validates_schema
    def check_units(self, commitment, **kwargs):
        baseline_field = self.declared_fields["baseline"]
        if "baseline" in commitment:
            baseline_unit = baseline_field._get_unit(commitment["baseline"])
        else:
            baseline_unit = "MW"
        if is_power_unit(baseline_unit):
            price_validators = [
                is_capacity_price_unit,
                is_energy_price_unit,
            ]  # one of these must pass
            allowed_price_units = ["power", "energy"]
        # todo: consider supporting more types of baselines here later
        # elif is_energy_unit(baseline_unit):
        #     baseline_validator = is_energy_unit
        #     price_validators = [is_energy_price_unit]
        #     unit_type = "energy"
        else:
            raise ValidationError(
                "Commitment baseline must have a power unit.",
                field_name="baseline",
            )

        def _ensure_variable_quantity_passes_one_validator(
            variable_quantity: ur.Quantity | Sensor | dict,
            validators: list[Callable],
            field_name: str,
            error_message: str,
        ):
            if not any(
                [
                    validate_variable_quantity(
                        variable_quantity=variable_quantity,
                        unit_validator=validator,
                        data_key=field_name,
                    )
                    for validator in validators
                ]
            ):
                raise ValidationError(
                    message=error_message,
                    field_name=field_name,
                )

        if "up_price" in commitment:
            _ensure_variable_quantity_passes_one_validator(
                variable_quantity=commitment["up_price"],
                validators=price_validators,
                field_name="up-price",
                error_message=f"Commitment up-price must have a {' or '.join(allowed_price_units)} unit in its denominator.",
            )
        if "down_price" in commitment:
            _ensure_variable_quantity_passes_one_validator(
                variable_quantity=commitment["down_price"],
                validators=price_validators,
                field_name="down-price",
                error_message=f"Commitment down-price must have a {' or '.join(allowed_price_units)} unit in its denominator.",
            )


class DBCommitmentSchema(CommitmentSchema, NoTimeSeriesSpecs):
    pass


class SharedSchema(Schema):
    """Shared schema for fields common across commodities in flex-context and commodity-context."""

    consumption_price = VariableQuantityField(
        "/MWh",
        required=False,
        data_key="consumption-price",
        return_magnitude=False,
        metadata=metadata.CONSUMPTION_PRICE.to_dict(),
    )

    production_price = VariableQuantityField(
        "/MWh",
        required=False,
        data_key="production-price",
        return_magnitude=False,
        metadata=metadata.PRODUCTION_PRICE.to_dict(),
    )

    ems_power_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-power-capacity",
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_POWER_CAPACITY.to_dict(),
    )

    ems_consumption_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-consumption-capacity",
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_CONSUMPTION_CAPACITY.to_dict(),
    )

    ems_production_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-production-capacity",
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_PRODUCTION_CAPACITY.to_dict(),
    )

    ems_consumption_breach_price = VariableQuantityField(
        "/MW",
        data_key="site-consumption-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_CONSUMPTION_BREACH_PRICE.to_dict(),
    )

    ems_production_breach_price = VariableQuantityField(
        "/MW",
        data_key="site-production-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_PRODUCTION_BREACH_PRICE.to_dict(),
    )

    ems_peak_consumption_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-peak-consumption",
        value_validator=validate.Range(min=0),
        load_default=ur.Quantity("0 kW"),
        metadata=metadata.SITE_PEAK_CONSUMPTION.to_dict(),
    )

    ems_peak_consumption_price = VariableQuantityField(
        "/MW",
        data_key="site-peak-consumption-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_PEAK_CONSUMPTION_PRICE.to_dict(),
    )

    ems_peak_production_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="site-peak-production",
        value_validator=validate.Range(min=0),
        load_default=ur.Quantity("0 kW"),
        metadata=metadata.SITE_PEAK_PRODUCTION.to_dict(),
    )

    ems_peak_production_price = VariableQuantityField(
        "/MW",
        data_key="site-peak-production-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SITE_PEAK_PRODUCTION_PRICE.to_dict(),
    )

    # Breach prices for device capacity constraints
    consumption_breach_price = VariableQuantityField(
        "/MW",
        data_key="consumption-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.CONSUMPTION_BREACH_PRICE.to_dict(),
    )
    production_breach_price = VariableQuantityField(
        "/MW",
        data_key="production-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.PRODUCTION_BREACH_PRICE.to_dict(),
    )
    soc_minima_breach_price = VariableQuantityField(
        "/MWh",
        data_key="soc-minima-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SOC_MINIMA_BREACH_PRICE.to_dict(),
    )
    soc_maxima_breach_price = VariableQuantityField(
        "/MWh",
        data_key="soc-maxima-breach-price",
        required=False,
        value_validator=validate.Range(min=0),
        metadata=metadata.SOC_MAXIMA_BREACH_PRICE.to_dict(),
    )

    # Relaxation fields
    relax_constraints = fields.Bool(
        data_key="relax-constraints",
        load_default=True,
        metadata=metadata.RELAX_CONSTRAINTS.to_dict(),
    )
    relax_soc_constraints = fields.Bool(
        data_key="relax-soc-constraints",
        load_default=False,
        metadata=metadata.RELAX_SOC_CONSTRAINTS.to_dict(),
    )
    relax_capacity_constraints = fields.Bool(
        data_key="relax-capacity-constraints",
        load_default=False,
        metadata=metadata.RELAX_CAPACITY_CONSTRAINTS.to_dict(),
    )
    relax_site_capacity_constraints = fields.Bool(
        data_key="relax-site-capacity-constraints",
        load_default=False,
        metadata=metadata.RELAX_SITE_CAPACITY_CONSTRAINTS.to_dict(),
    )

    commitments = fields.Nested(
        CommitmentSchema,
        data_key="commitments",
        required=False,
        many=True,
        metadata=metadata.COMMITMENTS.to_dict(),
    )

    inflexible_device_sensors = fields.List(
        SensorIdField(),
        data_key="inflexible-device-sensors",
        metadata=metadata.INFLEXIBLE_DEVICE_SENSORS.to_dict(),
    )

    # Aggregate output sensors
    aggregate_consumption = fields.Nested(
        OutputSensorReferenceSchema,
        required=False,
        data_key="aggregate-consumption",
        metadata=metadata.AGGREGATE_CONSUMPTION.to_dict(),
    )
    aggregate_production = fields.Nested(
        OutputSensorReferenceSchema,
        required=False,
        data_key="aggregate-production",
        metadata=metadata.AGGREGATE_PRODUCTION.to_dict(),
    )

    def set_default_breach_prices(
        self, data: dict, fields: list[str], price: ur.Quantity
    ):
        """Fill in default breach prices.

        This relies on _try_to_convert_price_units to run first, setting a shared currency unit.
        """
        for field in fields:
            # use the same denominator as defined in the field
            data[field] = price.to(
                data["shared_currency_unit"]
                + "/"
                + self.declared_fields[field].to_unit.split("/")[-1]
            )
        return data

    @validates_schema(pass_original=True)
    def _try_to_convert_price_units(self, data: dict, original_data: dict, **kwargs):
        """Convert price units to the same unit and scale if they can (incl. same currency)."""

        shared_currency_unit = None
        previous_field_name = None
        for field in self.declared_fields:
            if field[-5:] == "price" and field in data:
                price_field = self.declared_fields[field]
                price_unit = price_field._get_unit(data[field])
                currency_unit = str(
                    (
                        ur.Quantity(price_unit) / ur.Quantity(f"1{price_field.to_unit}")
                    ).units
                )

                if shared_currency_unit is None:
                    shared_currency_unit = str(
                        ur.Quantity(currency_unit).to_base_units().units
                    )
                    previous_field_name = price_field.data_key
                if not units_are_convertible(currency_unit, shared_currency_unit):
                    field_name = price_field.data_key
                    original_price_unit = price_field._get_original_unit(
                        original_data[field_name], data[field]
                    )
                    error_message = f"Invalid unit. A valid unit would be, for example, '{shared_currency_unit + price_field.to_unit}' (this example uses '{shared_currency_unit}', because '{previous_field_name}' used that currency). However, you passed an incompatible price ('{original_price_unit}') for the '{field_name}' field."
                    if shared_currency_unit not in price_unit:
                        error_message += f" Also note that all prices in the flex-context must share the same currency unit (in this case: '{shared_currency_unit}')."
                    raise ValidationError(error_message, field_name=field_name)
        if shared_currency_unit is not None:
            data["shared_currency_unit"] = shared_currency_unit
        elif sensor := data.get("consumption_price_sensor"):
            data["shared_currency_unit"] = self._to_currency_per_mwh(sensor.unit)
        elif sensor := data.get("production_price_sensor"):
            data["shared_currency_unit"] = self._to_currency_per_mwh(sensor.unit)
        else:
            # No user-given price fields at all: fall back to "EUR", but flag this
            # as a default (not user-given), so cross-context/cross-schema currency
            # comparisons can skip it (a price-free context should never trip a
            # currency-mismatch error against the rest of a differently-currencied
            # portfolio; see CommodityFlexContextSchema.fill_grid_connection_defaults
            # and FlexContextSchema.validate_commodity_contexts_shared_currency).
            data["shared_currency_unit"] = "EUR"
            data["shared_currency_unit_is_default"] = True
        return data

    # Currency-denominated fields that CommodityFlexContextSchema's smart defaults
    # (fill_grid_connection_defaults) may fill with a fallback "EUR" price/breach
    # price when a context has no user-given price fields at all.
    _CURRENCY_DENOMINATED_FIELDS = (
        "consumption_price",
        "production_price",
        "ems_consumption_breach_price",
        "ems_production_breach_price",
        "consumption_breach_price",
        "production_breach_price",
        "soc_minima_breach_price",
        "soc_maxima_breach_price",
        "ems_peak_consumption_price",
        "ems_peak_production_price",
    )

    @classmethod
    def _rebase_default_context_currency(cls, context: dict, new_currency: str):
        """Re-express a price-free context's fallback-currency fields in another currency.

        Only called for a commodity context that had no user-given price fields
        (``shared_currency_unit_is_default`` is True), once a real portfolio
        currency becomes known (e.g. from the top-level flex-context, or from a
        sibling commodity context). All of that context's currency-denominated
        fields were filled with plain quantities in a fallback "EUR", so their
        magnitudes carry over unchanged under the new currency label (no FX
        conversion is implied or attempted).
        """
        for field in cls._CURRENCY_DENOMINATED_FIELDS:
            value = context.get(field)
            if not isinstance(value, ur.Quantity):
                continue
            old_units = str(value.units)
            denominator = old_units.split("/", 1)[1] if "/" in old_units else None
            new_unit = (
                new_currency if denominator is None else f"{new_currency}/{denominator}"
            )
            context[field] = ur.Quantity(value.magnitude, new_unit)
        context["shared_currency_unit"] = new_currency
        context["shared_currency_unit_is_default"] = False

    @staticmethod
    def _to_currency_per_mwh(price_unit: str) -> str:
        """Convert a price unit to a base currency used to express that price per MWh.

        >>> FlexContextSchema()._to_currency_per_mwh("EUR/MWh")
        'EUR'
        >>> FlexContextSchema()._to_currency_per_mwh("EUR/kWh")
        'EUR'
        """
        currency = str(ur.Quantity(price_unit + " * MWh").to_base_units().units)
        return currency


class CommodityFlexContextSchema(SharedSchema):
    commodity = fields.Str(
        required=False,
        load_default="electricity",
        data_key="commodity",
        metadata=metadata.COMMODITY_FLEX_CONTEXT.to_dict(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        commodity_field = self.fields.pop("commodity")
        self.fields = OrderedDict(
            [("commodity", commodity_field), *self.fields.items()]
        )

    @post_load(pass_original=True)
    def fill_grid_connection_defaults(self, data: dict, original_data: dict, **kwargs):
        """Fill in smarter defaults for a commodity context's grid-connection fields.

        A commodity context (an entry of the top-level `commodities` list) may omit
        some or all of the grid-connection fields (`consumption-price`,
        `production-price`, `site-consumption-capacity`, `site-production-capacity`,
        `site-power-capacity`). Rather than leaving those simply unset (which, for
        `consumption-price`, would make the scheduler fail, since it requires one),
        we derive sensible defaults from *which* of those five fields were explicitly
        given (inspecting the original input, not post-default-fill presence).

        A price given for a direction (consumption or production) implies a grid
        connection in that direction, with an unlimited capacity unless a capacity
        is also given; a capacity given for a direction (without a price) implies a
        0 price in that direction; and anything not implied by a given field
        defaults to "no connection" (0 capacity, as a soft constraint). The
        exception is `site-power-capacity` given on its own, which sets a *hard*
        (symmetric) capacity limit instead. See :ref:`commodity_context_defaults`
        for the full user-facing explanation, including worked examples.

        Precedence (single-field triggers):

        1. None of the five given (e.g. just `{"commodity": "gas"}`): no grid
           connection at all. `site-consumption-capacity` and
           `site-production-capacity` default to 0, as *soft* constraints (a default
           breach price is filled in, so breaching is possible but penalized -- this
           relies on `relax-constraints`/`relax-site-capacity-constraints`, which
           default to True). `site-power-capacity` is left unlimited (unset).
        2. Only `consumption-price` given: assume a grid connection for consumption.
           `site-power-capacity` and `site-consumption-capacity` stay unlimited.
           `site-production-capacity` defaults to 0 (soft).
        3. Only `production-price` given: the mirror image of (2), for production.
        4. Only `site-consumption-capacity` given: `site-power-capacity` stays
           unlimited; `consumption-price` defaults to 0; `site-production-capacity`
           (and, transitively, `production-price`) default to 0.
        5. Only `site-production-capacity` given: the mirror image of (4).
        6. Only `site-power-capacity` given: a *hard* constraint at that capacity.
           `site-consumption-capacity` and `site-production-capacity` are both set
           equal to it (no breach price is filled in, so the constraint stays hard);
           `consumption-price` and `production-price` default to 0.

        As a safety net (since the scheduler requires a resolvable consumption
        price), `consumption-price` defaults to 0 if still unset after applying the
        rules above (`production-price` already falls back to `consumption-price`
        at the scheduler level, so no separate safety net is needed for it).

        A commodity context with no user-given price fields does not trip a spurious cross-currency error against a differently-currencied portfolio;
        its 0-price/breach-price fields instead inherit the portfolio's real currency where determinable (from a top-level price or a sibling commodity context).
        """

        has_consumption_price = "consumption-price" in original_data
        has_production_price = "production-price" in original_data
        has_consumption_capacity = "site-consumption-capacity" in original_data
        has_production_capacity = "site-production-capacity" in original_data
        has_power_capacity = "site-power-capacity" in original_data

        any_given = (
            has_consumption_price
            or has_production_price
            or has_consumption_capacity
            or has_production_capacity
            or has_power_capacity
        )

        currency = data.get("shared_currency_unit") or "EUR"
        zero_price = ur.Quantity(f"0 {currency}/MWh")
        zero_capacity = ur.Quantity("0 MW")

        # Case 6: site-power-capacity is the only field given -> hard constraint.
        if has_power_capacity and not (
            has_consumption_price
            or has_production_price
            or has_consumption_capacity
            or has_production_capacity
        ):
            power_capacity = data["ems_power_capacity_in_mw"]
            data.setdefault("ems_consumption_capacity_in_mw", power_capacity)
            data.setdefault("ems_production_capacity_in_mw", power_capacity)
            data.setdefault("consumption_price", zero_price)
            data.setdefault("production_price", zero_price)
            return data

        # Case 1: nothing given at all -> fully disconnected commodity.
        if not any_given:
            self._default_zero_capacity_as_soft_constraint(
                data, "ems_consumption_capacity_in_mw", zero_capacity
            )
            self._default_zero_capacity_as_soft_constraint(
                data, "ems_production_capacity_in_mw", zero_capacity
            )
            data.setdefault("consumption_price", zero_price)
            return data

        # Cases 2-5 and combinations thereof: fill in what's still missing, per
        # direction (consumption/production), independently.
        if not has_consumption_price and not has_consumption_capacity:
            self._default_zero_capacity_as_soft_constraint(
                data, "ems_consumption_capacity_in_mw", zero_capacity
            )
        if has_consumption_capacity and not has_consumption_price:
            data.setdefault("consumption_price", zero_price)

        if not has_production_price and not has_production_capacity:
            self._default_zero_capacity_as_soft_constraint(
                data, "ems_production_capacity_in_mw", zero_capacity
            )
        if has_production_capacity and not has_production_price:
            data.setdefault("production_price", zero_price)

        # Safety net: the scheduler requires a resolvable consumption price.
        data.setdefault("consumption_price", zero_price)

        return data

    def _default_zero_capacity_as_soft_constraint(
        self, data: dict, field: str, zero_capacity: ur.Quantity
    ):
        """Default a site capacity field to 0, as a *soft* constraint.

        Also fills in a default breach price for that direction (unless one was
        already set), so the 0 capacity is enforced as a soft constraint (breaching
        is possible, but penalized) rather than a hard, potentially infeasible, one.
        This mirrors FlexContextSchema.check_prices, but scoped to a single
        commodity context, and only fired for capacities defaulted here (not for
        capacities the caller explicitly set to 0).
        """
        if field in data:
            # Already set (e.g. by an earlier rule in this method); leave it as-is.
            return
        data[field] = zero_capacity

        breach_price_field = {
            "ems_consumption_capacity_in_mw": "ems_consumption_breach_price",
            "ems_production_capacity_in_mw": "ems_production_breach_price",
        }[field]
        if data.get("relax_site_capacity_constraints") or data.get("relax_constraints"):
            if not data.get(breach_price_field):
                currency = data.get("shared_currency_unit") or "EUR"
                shared_currency = ur.Quantity(currency)
                self.set_default_breach_prices(
                    data,
                    fields=[breach_price_field],
                    price=10000 * shared_currency / ur.Quantity("kW"),
                )
        elif data.get("relax_constraints") is False:
            # relax-constraints defaults to True, so False here can only be an
            # explicit user choice. Since relax-site-capacity-constraints is also
            # not set/true, this 0 capacity ends up as a *hard* constraint, which
            # is likely infeasible for any commodity with actual devices/flow.
            current_app.logger.warning(
                f"Commodity context '{data.get('commodity', 'electricity')}' has"
                f" its '{field}' defaulted to a 0 capacity, but"
                " 'relax-constraints' was explicitly set to False (and"
                " 'relax-site-capacity-constraints' was not set to True), so this"
                " ends up as a hard 0-capacity constraint, which is likely"
                " infeasible."
            )


class FlexContextSchema(SharedSchema):
    """This schema defines fields that provide context to the portfolio to be optimized."""

    # The single-dict flex-context form only supports the electricity commodity.
    # Other commodities must be defined via the `commodities` list.
    # Not part of the documented UI/OpenAPI fields.
    commodity = fields.Str(
        required=False,
        load_default="electricity",
        data_key="commodity",
        validate=validate.OneOf(
            ["electricity"],
            error="The top-level flex-context dict only supports the 'electricity' "
            "commodity. Use the `commodities` list to define other commodities.",
        ),
        metadata=dict(
            description="Commodity of the single-dict flex-context form; only 'electricity' is supported here. Use the `commodities` list to define other commodities.",
        ),
    )

    commodity_contexts = fields.Nested(
        CommodityFlexContextSchema,
        data_key="commodities",
        required=False,
        many=True,
        metadata=dict(
            description="For multi-commodity scheduling problems, the above fields can be set here per commodity.",
        ),
    )

    # Energy commitments
    # todo: deprecated since flexmeasures==0.23
    consumption_price_sensor = SensorIdField(data_key="consumption-price-sensor")
    production_price_sensor = SensorIdField(data_key="production-price-sensor")

    # todo: group by month start (MS), something like a commitment resolution, or a list of datetimes representing splits of the commitments
    aggregate_power = VariableQuantityField(
        to_unit="MW",
        data_key="aggregate-power",
        required=False,
        metadata=metadata.AGGREGATE_POWER.to_dict(),
    )

    @validates("aggregate_power")
    def validate_aggregate_power_is_sensor(
        self,
        aggregate_power: Sensor | SensorReference | list[dict] | ur.Quantity,
        **kwargs,
    ):
        if isinstance(aggregate_power, SensorReference):
            raise ValidationError(
                "The `aggregate-power` field cannot use source filters."
            )
        if not isinstance(aggregate_power, Sensor):
            raise ValidationError("The `aggregate-power` field can only be a Sensor.")

    @validates("commodity_contexts")
    def validate_commodity_contexts_unique(
        self, commodity_contexts: list[dict], **kwargs
    ):
        """Validate that each commodity is listed at most once.

        `_get_commodity_contexts` (storage.py) builds a dict keyed by commodity, so
        duplicate entries would otherwise silently overwrite each other.
        """
        commodities = [context["commodity"] for context in commodity_contexts]
        seen = set()
        duplicates = set()
        for commodity in commodities:
            if commodity in seen:
                duplicates.add(commodity)
            seen.add(commodity)
        if duplicates:
            raise ValidationError(
                f"Each commodity may only be listed once in `commodities`. Duplicate(s): {sorted(duplicates)}."
            )

    @validates("commodity_contexts")
    def validate_commodity_contexts_shared_currency(
        self, commodity_contexts: list[dict], **kwargs
    ):
        """Validate that all prices across commodity contexts share the same currency.

        Each commodity context already computed its own normalized ``shared_currency_unit``
        (a base-unit currency string, e.g. "EUR") via the inherited
        ``_try_to_convert_price_units`` schema-level validator. We simply compare those.
        """
        if not commodity_contexts:
            return

        shared_currency_unit = None

        for context in commodity_contexts:
            if context.get("shared_currency_unit_is_default"):
                # No user-given price fields in this context: its "EUR" currency is
                # just a fallback, not a real constraint, so don't let it clash with
                # a differently-currencied portfolio.
                continue
            context_currency_unit = context.get("shared_currency_unit")
            if context_currency_unit is None:
                continue
            if shared_currency_unit is None:
                shared_currency_unit = context_currency_unit
            elif not units_are_convertible(context_currency_unit, shared_currency_unit):
                raise ValidationError(
                    "all prices in the flex-context must share the same currency unit"
                    f" (found both '{shared_currency_unit}' and '{context_currency_unit}')"
                )

    # Note: we deliberately tolerate a `commodities` list combined with top-level
    # commodity-specific (SharedSchema) fields. In the API path, a multi-commodity
    # list is normalized to {"commodities": [...]} and collect_flex_config then
    # dict-merges the asset's db-stored flex-context (e.g. "site-power-capacity",
    # "consumption-price") at the top level, so rejecting this mix would 422 any
    # asset with stored electricity flex-context fields. Semantics: top-level fields
    # serve as the electricity context only when the commodities list has no
    # electricity entry (see _get_commodity_contexts in storage.py).

    def _reconcile_commodity_context_currencies(self, data: dict) -> str:
        """Backfill price-free contexts' currency with the portfolio's real currency.

        Determines the portfolio's real (user-given) shared currency, if any: the
        top-level one, unless it's itself just a fallback (no user-given price
        fields at the top level), in which case falls back to the first
        non-default commodity context's currency, if any. Then rebases any
        price-free ("default currency") commodity context onto that real currency,
        so their 0-price/breach-price fills inherit it. Returns the (possibly
        just-updated) top-level `shared_currency_unit`.
        """
        commodity_contexts = data.get("commodity_contexts", []) or []
        real_shared_currency_unit = None
        if not data.get("shared_currency_unit_is_default"):
            real_shared_currency_unit = data["shared_currency_unit"]
        else:
            for context in commodity_contexts:
                if not context.get("shared_currency_unit_is_default"):
                    real_shared_currency_unit = context["shared_currency_unit"]
                    break

        if real_shared_currency_unit is not None and data.get(
            "shared_currency_unit_is_default"
        ):
            data["shared_currency_unit"] = real_shared_currency_unit
            data["shared_currency_unit_is_default"] = False

        if real_shared_currency_unit is not None:
            for context in commodity_contexts:
                if context.get("shared_currency_unit_is_default"):
                    self._rebase_default_context_currency(
                        context, real_shared_currency_unit
                    )

        return data["shared_currency_unit"]

    def _check_deprecated_price_sensor_migration(self, data: dict, original_data: dict):
        """New price fields can only be used after updating to consumption-price/production-price."""
        field_map = {
            field.data_key: field_var
            for field_var, field in self.declared_fields.items()
        }
        # Only count fields that were explicitly passed (not filled in by a load_default,
        # such as relax-constraints, which defaults to True).
        if any(
            field in original_data and data.get(field_map[field])
            for field in (
                "soc-minima-breach-price",
                "soc-maxima-breach-price",
                "site-consumption-breach-price",
                "site-production-breach-price",
                "site-peak-consumption-price",
                "site-peak-production-price",
                "relax-constraints",
                "relax-soc-constraints",
                "relax-capacity-constraints",
                "relax-site-capacity-constraints",
                "consumption-breach-price",
                "production-breach-price",
            )
        ):
            if field_map["consumption-price-sensor"] in data:
                raise ValidationError(
                    f"""Please switch to using `consumption-price: {{"sensor": {data[field_map["consumption-price-sensor"]].id}}}`."""
                )
            if field_map["production-price-sensor"] in data:
                raise ValidationError(
                    f"""Please switch to using `production-price: {{"sensor": {data[field_map["production-price-sensor"]].id}}}`."""
                )

    @validates_schema(pass_original=True)
    def check_prices(self, data: dict, original_data: dict, **kwargs):
        """Check assumptions about prices.

        1. The flex-context must contain at most 1 consumption price and at most 1 production price field.
        2. All prices must share the same currency.
        """

        # The flex-context must contain at most 1 consumption price and at most 1 production price field
        if "consumption_price_sensor" in data and "consumption_price" in data:
            raise ValidationError(
                "Must pass either consumption-price or consumption-price-sensor."
            )
        if "production_price_sensor" in data and "production_price" in data:
            raise ValidationError(
                "Must pass either production-price or production-price-sensor."
            )

        self._check_deprecated_price_sensor_migration(data, original_data)

        # make sure that the prices fields are valid price units

        # All prices must share the same unit
        data = self._try_to_convert_price_units(data, original_data)
        shared_currency = ur.Quantity(
            self._reconcile_commodity_context_currencies(data)
        )

        # Also check that top-level prices share their currency with any per-commodity contexts
        for context in data.get("commodity_contexts", []) or []:
            if context.get("shared_currency_unit_is_default"):
                # Already reconciled (or left as a harmless fallback, if no real
                # currency was determinable anywhere) by
                # _reconcile_commodity_context_currencies above.
                continue
            context_currency_unit = context.get("shared_currency_unit")
            if context_currency_unit is None:
                continue
            if not units_are_convertible(
                context_currency_unit, data["shared_currency_unit"]
            ):
                raise ValidationError(
                    "all prices in the flex-context must share the same currency unit"
                    f" (found both '{data['shared_currency_unit']}' at the top level and"
                    f" '{context_currency_unit}' in a commodity context)",
                    field_name="commodities",
                )

        # Skip filling default breach prices when:
        # - the deprecated price sensor fields are used (those predate relaxation
        #   support; filling defaults would silently change legacy behaviour), or
        # - the shared currency is not an actual currency (e.g. a mis-united price
        #   field slipped through _try_to_convert_price_units); filling defaults in a
        #   nonsense currency would misattribute unit errors to the breach price
        #   fields in downstream validation (e.g. DBFlexContextSchema).
        if (
            "consumption_price_sensor" in data
            or "production_price_sensor" in data
            or not is_currency_unit(data["shared_currency_unit"])
        ):
            return data

        # Fill in default soc breach prices when asked to relax SoC constraints, unless already set explicitly.
        if (
            data["relax_soc_constraints"]
            or data["relax_constraints"]
            and not data.get("soc_minima_breach_price")
            and not data.get("soc_maxima_breach_price")
        ):
            self.set_default_breach_prices(
                data,
                fields=["soc_minima_breach_price", "soc_maxima_breach_price"],
                price=1000 * shared_currency / ur.Quantity("kWh"),
            )

        # Fill in default capacity breach prices when asked to relax capacity constraints, unless already set explicitly.
        if (
            data["relax_capacity_constraints"]
            or data["relax_constraints"]
            and not data.get("consumption_breach_price")
            and not data.get("production_breach_price")
        ):
            self.set_default_breach_prices(
                data,
                fields=["consumption_breach_price", "production_breach_price"],
                price=100 * shared_currency / ur.Quantity("kW"),
            )

        # Fill in default site capacity breach prices when asked to relax site capacity constraints, unless already set explicitly.
        if (
            data["relax_site_capacity_constraints"]
            or data["relax_constraints"]
            and not data.get("ems_consumption_breach_price")
            and not data.get("ems_production_breach_price")
        ):
            self.set_default_breach_prices(
                data,
                fields=["ems_consumption_breach_price", "ems_production_breach_price"],
                price=10000 * shared_currency / ur.Quantity("kW"),
            )

        return data


EXAMPLE_UNIT_TYPES: Dict[str, list[str]] = {
    "commodity": ["electricity", "gas"],
    "energy-price": ["EUR/MWh", "JPY/kWh", "USD/MWh", "and other currencies."],
    "power-price": ["EUR/kW", "JPY/kW", "USD/kW", "and other currencies."],
    "power": ["MW", "kW"],
    "energy": ["MWh", "kWh"],
    "boolean": ["Boolean"],
    "efficiency": ["%"],
}

UI_FLEX_CONTEXT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "aggregate-consumption": {
        "default": None,
        "description": rst_to_openapi(metadata.AGGREGATE_CONSUMPTION.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "aggregate-production": {
        "default": None,
        "description": rst_to_openapi(metadata.AGGREGATE_PRODUCTION.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "consumption-price": {
        "default": None,  # Refers to default value of the field
        "description": rst_to_openapi(metadata.CONSUMPTION_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["energy-price"],
    },
    "production-price": {
        "default": None,
        "description": rst_to_openapi(metadata.PRODUCTION_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["energy-price"],
    },
    "site-power-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_POWER_CAPACITY.description),
        "example-units": ["kVA", "MVA"] + EXAMPLE_UNIT_TYPES["power"],
    },
    "site-production-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_PRODUCTION_CAPACITY.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "site-consumption-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_CONSUMPTION_CAPACITY.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "soc-minima-breach-price": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MINIMA_BREACH_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["energy-price"],
    },
    "soc-maxima-breach-price": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MAXIMA_BREACH_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["energy-price"],
    },
    "consumption-breach-price": {
        "default": None,
        "description": rst_to_openapi(metadata.CONSUMPTION_BREACH_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "production-breach-price": {
        "default": None,
        "description": rst_to_openapi(metadata.PRODUCTION_BREACH_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "site-consumption-breach-price": {
        "default": None,
        "description": rst_to_openapi(
            metadata.SITE_CONSUMPTION_BREACH_PRICE.description
        ),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "site-production-breach-price": {
        "default": None,
        "description": rst_to_openapi(
            metadata.SITE_PRODUCTION_BREACH_PRICE.description
        ),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "site-peak-consumption": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_PEAK_CONSUMPTION.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "site-peak-production": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_PEAK_PRODUCTION.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "site-peak-consumption-price": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_PEAK_CONSUMPTION_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "site-peak-production-price": {
        "default": None,
        "description": rst_to_openapi(metadata.SITE_PEAK_PRODUCTION_PRICE.description),
        "example-units": EXAMPLE_UNIT_TYPES["power-price"],
    },
    "inflexible-device-sensors": {
        "default": [],
        "description": rst_to_openapi(metadata.INFLEXIBLE_DEVICE_SENSORS.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "commitments": {
        "default": None,
        "description": rst_to_openapi(metadata.COMMITMENTS.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "aggregate-power": {
        "default": None,
        "description": rst_to_openapi(metadata.AGGREGATE_POWER.description),
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
}

UI_FLEX_MODEL_SCHEMA: Dict[str, Dict[str, Any]] = {
    "consumption": {
        "default": None,
        "description": rst_to_openapi(metadata.CONSUMPTION.description),
        "types": {
            "backend": "typeTwo",
            "ui": "A sensor which records the scheduled consumption.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "production": {
        "default": None,
        "description": rst_to_openapi(metadata.PRODUCTION.description),
        "types": {
            "backend": "typeTwo",
            "ui": "A sensor which records the scheduled production.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "soc-min": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MIN.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "soc-max": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MAX.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "soc-minima": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MINIMA.description),
        "types": {
            "backend": "typeTwo",
            "ui": "A sensor which records the state of charge.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "soc-maxima": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_MAXIMA.description),
        "types": {
            "backend": "typeTwo",
            "ui": "A sensor which records the state of charge.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "soc-targets": {
        "default": None,
        "description": rst_to_openapi(metadata.SOC_TARGETS.description),
        "types": {
            "backend": "typeTwo",
            "ui": "A sensor which records the state of charge.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "state-of-charge": {
        "default": None,
        "description": rst_to_openapi(metadata.STATE_OF_CHARGE.description),
        "types": {
            "backend": "typeTwo",
            "ui": "A sensor which records the state of charge.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["energy"],
    },
    "soc-gain": {
        "default": [],
        "description": rst_to_openapi(metadata.SOC_GAIN.description),
        "types": {
            "backend": "typeFour",
            "ui": "Multiple settings possible - either fixed values or dynamic signals (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "soc-usage": {
        "default": [],
        "description": rst_to_openapi(metadata.SOC_USAGE.description),
        "types": {
            "backend": "typeFour",
            "ui": "Multiple settings possible - either fixed values or dynamic signals (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "roundtrip-efficiency": {
        "default": None,
        "description": rst_to_openapi(metadata.ROUNDTRIP_EFFICIENCY.description),
        "types": {
            "backend": "typeFive",
            "ui": "Fixed value only.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["efficiency"],
    },
    "charging-efficiency": {
        "default": None,
        "description": rst_to_openapi(metadata.CHARGING_EFFICIENCY.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["efficiency"],
    },
    "discharging-efficiency": {
        "default": None,
        "description": rst_to_openapi(metadata.DISCHARGING_EFFICIENCY.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["efficiency"],
    },
    "storage-efficiency": {
        "default": None,
        "description": rst_to_openapi(metadata.STORAGE_EFFICIENCY.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["efficiency"],
    },
    "prefer-charging-sooner": {
        "default": None,
        "description": rst_to_openapi(metadata.PREFER_CHARGING_SOONER.description),
        "types": {
            "backend": "typeOne",
            "ui": "Boolean option only.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["boolean"],
    },
    "prefer-curtailing-later": {
        "default": None,
        "description": rst_to_openapi(metadata.PREFER_CURTAILING_LATER.description),
        "types": {
            "backend": "typeOne",
            "ui": "Boolean option only.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["boolean"],
    },
    "power-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.POWER_CAPACITY.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "consumption-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.CONSUMPTION_CAPACITY.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "production-capacity": {
        "default": None,
        "description": rst_to_openapi(metadata.PRODUCTION_CAPACITY.description),
        "types": {
            "backend": "typeThree",
            "ui": "One fixed value or a dynamic signal (via a sensor).",
        },
        "example-units": EXAMPLE_UNIT_TYPES["power"],
    },
    "commodity": {
        "default": "electricity",
        "description": rst_to_openapi(metadata.COMMODITY_FLEX_MODEL.description),
        "types": {
            "backend": "typeOne",
            "ui": "One fixed value only.",
        },
        "example-units": EXAMPLE_UNIT_TYPES["commodity"],
    },
}


class DBFlexContextSchema(FlexContextSchema, NoTimeSeriesSpecs):

    commitments = fields.Nested(
        DBCommitmentSchema, data_key="commitments", required=False, many=True
    )
    mapped_schema_keys = {
        field: FlexContextSchema().declared_fields[field].data_key
        for field in FlexContextSchema().declared_fields
    }

    @validates_schema
    def validate_fields_unit(self, data: dict, **kwargs):
        """Check that each field value has a valid unit."""

        self._validate_price_fields(data)
        self._validate_power_fields(data)
        self._validate_inflexible_device_sensors(data)

    def _validate_price_fields(self, data: dict):
        """Validate price fields."""
        energy_price_fields = [
            "consumption_price",
            "production_price",
            "soc_minima_breach_price",
            "soc_maxima_breach_price",
        ]
        capacity_price_fields = [
            "consumption_breach_price",
            "production_breach_price",
            "ems_consumption_breach_price",
            "ems_production_breach_price",
            "ems_peak_consumption_price",
            "ems_peak_production_price",
        ]

        # Check that consumption and production prices are Sensors
        self._forbid_fixed_prices(data)

        for field in energy_price_fields:
            if field in data:
                self._validate_field(data, "energy price", field, is_energy_price_unit)
        for field in capacity_price_fields:
            if field in data:
                self._validate_field(
                    data, "capacity price", field, is_capacity_price_unit
                )

    def _validate_power_fields(self, data: dict):
        """Validate power fields."""
        power_fields = [
            "ems_power_capacity_in_mw",
            "ems_production_capacity_in_mw",
            "ems_consumption_capacity_in_mw",
            "ems_peak_consumption_in_mw",
            "ems_peak_production_in_mw",
        ]

        for field in power_fields:
            if field in data:
                self._validate_field(data, "power", field, is_power_unit)

    def _validate_field(self, data: dict, field_type: str, field: str, unit_validator):
        """Validate fields based on type and unit validator."""

        if isinstance(data[field], ur.Quantity):
            if not unit_validator(str(data[field].units)):
                raise ValidationError(
                    f"{field_type.capitalize()} field '{self.mapped_schema_keys[field]}' must have {p.a(field_type)} unit.",
                    field_name=self.mapped_schema_keys[field],
                )
        elif isinstance(data[field], (Sensor, SensorReference)):
            if not unit_validator(data[field].unit):
                raise ValidationError(
                    f"{field_type.capitalize()} field '{self.mapped_schema_keys[field]}' must have {p.a(field_type)} unit.",
                    field_name=self.mapped_schema_keys[field],
                )

    def _validate_inflexible_device_sensors(self, data: dict):
        """Validate inflexible device sensors."""
        if "inflexible_device_sensors" in data:
            for sensor in data["inflexible_device_sensors"]:
                if not is_power_unit(sensor.unit) and not is_energy_unit(sensor.unit):
                    raise ValidationError(
                        f"Inflexible device sensor '{sensor.id}' must have a power or energy unit.",
                        field_name="inflexible-device-sensors",
                    )

    def _forbid_fixed_prices(self, data: dict, **kwargs):
        """Do not allow fixed consumption price or fixed production price in the flex-context fields saved in the db.

        This is a temporary restriction as future iterations will allow fixed prices on these fields as well.
        """
        if "consumption_price" in data and isinstance(
            data["consumption_price"], ur.Quantity
        ):
            raise ValidationError(
                "Fixed prices are not currently supported for consumption-price in flex-context fields in the DB.",
                field_name="consumption-price",
            )

        if "production_price" in data and isinstance(
            data["production_price"], ur.Quantity
        ):
            raise ValidationError(
                "Fixed prices are not currently supported for production-price in flex-context fields in the DB.",
                field_name="production-price",
            )


# One UI description per backend type token (same tokens as UI_FLEX_MODEL_SCHEMA uses).
UI_TYPE_DESCRIPTIONS: Dict[str, str] = {
    "typeOne": "One fixed value only.",
    "typeTwo": "One dynamic signal (via a sensor) only.",
    "typeThree": "One fixed value or a dynamic signal (via a sensor).",
    "typeFour": "A list of sensors.",
    "typeFive": "One fixed string value only.",
    "typeSix": "A list of structured entries.",
}


def _derive_backend_type(schema_field: fields.Field) -> str:
    """Derive the UI editor's backend type token from a marshmallow field."""
    if isinstance(schema_field, fields.Bool):
        return "typeOne"
    if isinstance(schema_field, fields.List):
        return "typeFour"
    if isinstance(schema_field, fields.Nested):
        return "typeSix" if schema_field.many else "typeTwo"
    if isinstance(schema_field, VariableQuantityField):
        return "typeThree"
    if isinstance(schema_field, fields.Str):
        return "typeFive"
    raise NotImplementedError(
        f"Cannot derive a UI type for field {schema_field.data_key}."
    )


# Fill in the "types" of each UI flex-context schema entry by deriving them
# from the corresponding DBFlexContextSchema field, so the UI editor stays in
# sync with what the DB schema actually accepts.
_db_flex_context_fields: Dict[str, fields.Field] = {
    schema_field.data_key or field_name: schema_field
    for field_name, schema_field in DBFlexContextSchema().fields.items()
}
for _field_name, _entry in UI_FLEX_CONTEXT_SCHEMA.items():
    _backend_type = _derive_backend_type(_db_flex_context_fields[_field_name])
    if _field_name in ("consumption-price", "production-price", "aggregate-power"):
        # Fixed prices are forbidden when storing the flex-context in the DB
        # (see DBFlexContextSchema._forbid_fixed_prices), and aggregate-power
        # must reference a sensor (see validate_aggregate_power_is_sensor),
        # so the editor only offers a sensor for these fields.
        _backend_type = "typeTwo"
    _entry["types"] = {
        "backend": _backend_type,
        "ui": UI_TYPE_DESCRIPTIONS[_backend_type],
    }


class MultiSensorFlexModelSchema(Schema):
    """

    This schema is agnostic to the underlying type of flex-model, which is governed by the chosen Scheduler instead.
    Therefore, the underlying type of flex-model is not deserialized.

    So:

        {
            "sensor": 1,
            "soc-at-start": "10 kWh"
        }

    becomes:

        {
            "sensor": <Sensor 1>,
            "sensor_flex_model": {
                "soc-at-start": "10 kWh"
            }
        }
    """

    sensor = SensorIdField(required=False)
    asset = GenericAssetIdField(required=False)
    # it's up to the Scheduler to deserialize the underlying flex-model
    sensor_flex_model = fields.Dict(data_key="sensor-flex-model")

    @validates_schema
    def ensure_sensor_or_asset(self, data, **kwargs):
        if (
            "sensor" in data
            and "asset" in data
            and data["sensor"].asset != data["asset"]
        ):
            raise ValidationError("Sensor does not belong to asset.")
        # if (
        #     "state-of-charge" in data["sensor_flex_model"]
        #     and "asset" in data
        #     and data["sensor_flex_model"]["state-of-charge"].asset != data["asset"]
        # ):
        #     raise ValidationError("Sensor does not belong to asset.")
        if (
            "sensor" not in data
            and "state-of-charge" not in data["sensor_flex_model"]
            and "asset" not in data
        ):
            raise ValidationError("Specify either a sensor or an asset.")

    @pre_load
    def unwrap_envelope(self, data, **kwargs):
        """Any field other than 'sensor' and 'asset' becomes part of the sensor's flex-model."""
        extra = {}
        rest = {}
        for k, v in data.items():
            if k not in self.fields:
                extra[k] = v
            else:
                rest[k] = v
        return {"sensor-flex-model": extra, **rest}

    @post_dump
    def wrap_with_envelope(self, data, **kwargs):
        """Any field in the 'sensor-flex-model' field becomes a main field."""
        sensor_flex_model = data.pop("sensor-flex-model", {})
        return dict(**data, **sensor_flex_model)


class AssetTriggerSchema(Schema):
    """
    {
        "start": "2025-01-21T15:00+01",
        "flex-model": [
            {
                "sensor": 1,
                "soc-at-start": "10 kWh"
            },
            {
                "sensor": 2,
                "soc-at-start": "20 kWh"
            },
        ]
    }
    """

    asset = GenericAssetIdField(
        data_key="id",
        metadata=dict(
            description="ID of the asset that is requested to be scheduled. Together with its children and their further offspring, the asset may represent a tree of assets, in which case the whole asset tree will be taken into account.",
        ),
    )
    start_of_schedule = AwareDateTimeField(
        data_key="start",
        format="iso",
        required=True,
        metadata=dict(
            description="Start time of the schedule, in ISO 8601 datetime format.",
            example="2026-01-15T10:00+01:00",
        ),
    )
    belief_time = AwareDateTimeField(
        format="iso",
        data_key="prior",
        description="The scheduler is only allowed to take into account sensor data that has been recorded prior to this [belief time](https://flexmeasures.readthedocs.io/latest/api/notation.html#tracking-the-recording-time-of-beliefs). "
        "By default, the most recent sensor data is used. This field is especially useful for running simulations.",
        example="2026-01-15T10:00+01:00",
    )
    duration = PlanningDurationField(
        load_default=PlanningDurationField.load_default,
        metadata=dict(
            description="The duration for which to create the schedule, also known as the planning horizon, in ISO 8601 duration format.",
            example="PT24H",
        ),
    )
    resolution = DurationField(
        metadata=dict(
            description="The resolution of the requested schedule in ISO 8601 duration format. "
            "This governs how often setpoints are allowed to change. "
            "Note that the resulting schedule is still saved in the resolution of each individual sensor.",
            example="PT2H",
        )
    )
    flex_model = fields.List(
        fields.Nested(MultiSensorFlexModelSchema()),
        data_key="flex-model",
        load_default=[],
    )
    flex_context = fields.Raw(
        required=False,
        data_key="flex-context",
        load_default={},
    )
    sequential = fields.Bool(
        load_default=False,
        metadata=dict(
            description="If true, each asset within the asset tree is scheduled one after the other, where the next schedule takes into account the previously scheduled assets as inflexible device.",
        ),
    )
    force_new_job_creation = fields.Boolean(
        data_key="force-new-job-creation",
        required=False,
        metadata=dict(
            description="If True, this bypasses the cache that the server keeps for results of scheduling jobs. This cache helps prevents redundant computation when schedules with the exact same request parameters are triggered.",
        ),
    )

    @pre_load
    def normalize_flex_context_format(self, data, **kwargs):
        """Normalize flex_context to always be a dict.

        Accepts both:
        - Single commodity dict: {"commodity": "electricity", ...}
        - List of commodity dicts: [{"commodity": "electricity", ...}, {"commodity": "heat", ...}]
        - MultiDict with multiple 'flex-context' entries (when JSON list is parsed by webargs)

        If a list is provided, it is wrapped under the 'commodities' field.
        If a dict is provided, it is kept as-is.
        This ensures downstream code always sees a dict structure.
        """
        if "flex-context" in data:
            raw_flex_context = data.get("flex-context")

            # Check if data is a MultiDict with multiple 'flex-context' entries
            # This happens when JSON contains a list which webargs converts to multiple entries
            if hasattr(data, "getlist"):
                # MultiDict case - get all values for 'flex-context'
                flex_contexts = data.getlist("flex-context")
                if len(flex_contexts) > 1:
                    # Multiple commodities: wrap in a dict with commodity_contexts field
                    data["flex-context"] = {"commodities": flex_contexts}
                # If only 1 entry, leave as-is (it's already a dict)
            elif isinstance(raw_flex_context, list):
                # Regular list case
                data["flex-context"] = {"commodities": raw_flex_context}
            # else: already a dict, leave as-is

            # By now, flex-context should always be normalized to a dict. If it isn't
            # (e.g. a bare string or number was passed), raise a 422 here instead of
            # letting downstream code fail with a TypeError.
            if not isinstance(data["flex-context"], dict):
                raise ValidationError(
                    "`flex-context` must be an object, or a list of objects.",
                    field_name="flex-context",
                )
        return data

    @validates_schema
    def check_flex_model_sensors(self, data, **kwargs):
        """Verify that the flex-model's sensors live under the asset for which a schedule is triggered."""
        asset = data["asset"]
        sensors = []
        for sensor_flex_model in data.get("flex_model", []):
            sensor = sensor_flex_model["sensor"]
            if sensor in sensors:
                raise FMValidationError(
                    f"Sensor {sensor_flex_model['sensor'].id} should not occur more than once in the flex-model"
                )
            if sensor.generic_asset not in [asset] + asset.offspring:
                raise FMValidationError(
                    f"Sensor {sensor_flex_model['sensor'].id} does not belong to asset {asset.id} (or to one of its offspring)"
                )
            sensors.append(sensor)
        return data


class ScheduleSignConvention:
    """Named constants for the three sign-convention modes of the get_schedule endpoint.

    :cvar CONSUMPTION_POSITIVE: Always return schedules with consumption as positive values
                                and production as negative values.  This is the default and
                                matches the view a *consumer* has of their device.
    :cvar PRODUCTION_POSITIVE: Always return schedules with production as positive values
                               and consumption as negative values.  This matches the view a
                               *producer* (or generator) has of their device.
    :cvar WYSIWYG: Return the raw values from the database without any sign inversion,
                   regardless of the sensor's ``consumption_is_positive`` attribute.
                   Useful when you want to see exactly what was stored.
    """

    CONSUMPTION_POSITIVE = "consumption-positive"
    PRODUCTION_POSITIVE = "production-positive"
    WYSIWYG = "wysiwyg"

    ALL = (CONSUMPTION_POSITIVE, PRODUCTION_POSITIVE, WYSIWYG)


class GetScheduleSchema(Schema):
    sensor = SensorIdField(required=True, data_key="id")
    job_id = fields.Str(required=True, data_key="uuid")
    duration = DurationField(load_default=timedelta(hours=6))
    unit = UnitField(load_default=None)
    sign_convention = fields.Str(
        data_key="sign-convention",
        load_default=ScheduleSignConvention.CONSUMPTION_POSITIVE,
        validate=validate.OneOf(ScheduleSignConvention.ALL),
        metadata=dict(
            description=(
                "Controls the sign convention applied to schedule values in the response. "
                f"``{ScheduleSignConvention.CONSUMPTION_POSITIVE}`` (default): consumption is always returned as positive values "
                f"and production as negative values. "
                f"``{ScheduleSignConvention.PRODUCTION_POSITIVE}``: production is always returned as positive values "
                f"and consumption as negative values. "
                f"``{ScheduleSignConvention.WYSIWYG}``: returns values with the same sign as database values and as seen in the UI charts, "
                "without adjusting their sign for the sensor's ``consumption_is_positive`` attribute."
            ),
            example=ScheduleSignConvention.CONSUMPTION_POSITIVE,
        ),
    )

    @post_load
    def finalize_unit_and_duration(self, data, **kwargs):
        sensor = data["sensor"]
        unit = data.get("unit")

        if unit is None:
            data["unit"] = sensor.unit
        elif unit != sensor.unit and not units_are_convertible(
            sensor.unit,
            unit,
            duration_known=True if sensor.event_resolution != timedelta(0) else False,
        ):
            raise ValidationError(
                f"Incompatible units: {sensor.unit} cannot be converted to {unit}.",
                field_name="unit",
            )

        duration = data["duration"]

        data["duration"] = DurationField.ground_from(
            duration,
            data.get("start", data.get("datetime")),
        )

        return data
