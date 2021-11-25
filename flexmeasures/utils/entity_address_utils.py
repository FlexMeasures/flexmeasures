import logging
from typing import Optional, Union
from urllib.parse import urlparse

import re
from tldextract import extract as tld_extract
from tldextract.tldextract import ExtractResult as TldExtractResult
from flask import request, current_app, has_request_context

from flexmeasures.utils.time_utils import get_first_day_of_next_month


"""
Functionality to support parsing and building Entity Addresses as defined by USEF [1].
See our documentation for more details.

[1] https://www.usef.energy/app/uploads/2020/01/USEF-Flex-Trading-Protocol-Specifications-1.01.pdf
"""


ADDR_SCHEME = "ea1"
FM1_ADDR_SCHEME = "fm1"
FM0_ADDR_SCHEME = "fm0"


class EntityAddressException(Exception):
    pass


def get_host() -> str:
    """Get host from the context of the request.

    Strips off www. but keeps subdomains.
    Can be localhost, too.
    """
    if has_request_context():
        host = urlparse(request.url).netloc.lstrip("www.")
        if host[:9] != "127.0.0.1":
            return host
    # Assume localhost (for CLI/tests/simulations)
    return "localhost"


def build_entity_address(
    entity_info: dict,
    entity_type: str,
    host: Optional[str] = None,
    fm_scheme: str = FM1_ADDR_SCHEME,
) -> str:
    """
    Build an entity address.

    fm1 type entity address should use entity_info["sensor_id"]
    todo: implement entity addresses for actuators with entity_info["actuator_id"] (first ensuring globally unique ids across sensors and actuators)

    If the host is not given, it is attempted to be taken from the request.
    entity_info is expected to contain the required fields for the custom string.

    Returns the address as string.
    """
    if host is None:
        host = get_host()

    def build_field(field: str, required: bool = True):
        if required and field not in entity_info:
            raise EntityAddressException(
                f"Cannot find required field '{field}' to build entity address."
            )
        if field not in entity_info:
            return ""
        return f"{entity_info[field]}:"

    if fm_scheme == FM1_ADDR_SCHEME:  # and entity_type == "sensor":
        locally_unique_str = f"{build_field('sensor_id')}"
    # elif fm_scheme == FM1_ADDR_SCHEME and entity_type == "actuator":
    #     locally_unique_str = f"{build_field('actuator_id')}"
    elif fm_scheme != FM0_ADDR_SCHEME:
        raise EntityAddressException(
            f"Unrecognized FlexMeasures scheme for entity addresses: {fm_scheme}"
        )
    elif entity_type == "connection":
        locally_unique_str = (
            f"{build_field('owner_id', required=False)}{build_field('asset_id')}"
        )
    elif entity_type == "weather_sensor":
        locally_unique_str = f"{build_field('weather_sensor_type_name')}{build_field('latitude')}{build_field('longitude')}"
    elif entity_type == "market":
        locally_unique_str = f"{build_field('market_name')}"
    elif entity_type == "event":
        locally_unique_str = f"{build_field('owner_id', required=False)}{build_field('asset_id')}{build_field('event_id')}{build_field('event_type')}"
    else:
        raise EntityAddressException(f"Unrecognized entity type: {entity_type}")
    return (
        build_ea_scheme_and_naming_authority(host)
        + ":"
        + fm_scheme
        + "."
        + locally_unique_str.rstrip(":")
    )


def parse_entity_address(  # noqa: C901
    entity_address: str,
    entity_type: str,
    fm_scheme: str = FM1_ADDR_SCHEME,
) -> dict:
    """
    Parses an entity address into an info dict.

    Returns a dictionary with scheme, naming_authority and various other fields,
    depending on the entity type and FlexMeasures scheme (see examples above).
    Returns None if entity type is unknown or entity_address is not parse-able.
    We recommend to `return invalid_domain()` in that case.

    Examples for the fm1 scheme:

        sensor = ea1.2021-01.io.flexmeasures:fm1.42
        sensor = ea1.2021-01.io.flexmeasures:fm1.<sensor_id>
        connection = ea1.2021-01.io.flexmeasures:fm1.<sensor_id>
        market = ea1.2021-01.io.flexmeasures:fm1.<sensor_id>
        weather_station = ea1.2021-01.io.flexmeasures:fm1.<sensor_id>
        todo: UDI events are not yet modelled in the fm1 scheme, but will probably be ea1.2021-01.io.flexmeasures:fm1.<actuator_id>

    Examples for the fm0 scheme:

        connection = ea1.2021-01.localhost:fm0.40:30
        connection = ea1.2021-01.io.flexmeasures:fm0.<owner_id>:<asset_id>
        weather_sensor = ea1.2021-01.io.flexmeasures:fm0.temperature:52:73.0
        weather_sensor = ea1.2021-01.io.flexmeasures:fm0.<sensor_type>:<latitude>:<longitude>
        market = ea1.2021-01.io.flexmeasures:fm0.epex_da
        market = ea1.2021-01.io.flexmeasures:fm0.<market_name>
        event = ea1.2021-01.io.flexmeasures:fm0.40:30:302:soc
        event = ea1.2021-01.io.flexmeasures:fm0.<owner_id>:<asset_id>:<event_id>:<event_type>

    For the fm0 scheme, the 'fm0.' part is optional, for backwards compatibility.
    """

    # Check the scheme and naming authority date
    if not entity_address.startswith(ADDR_SCHEME):
        raise EntityAddressException(
            f"A valid type 1 USEF entity address starts with '{ADDR_SCHEME}', please review {entity_address}"
        )
    date_regex = r"([0-9]{4})-(0[1-9]|1[012])"
    if not re.search(fr"^{date_regex}$", entity_address[4:11]):
        raise EntityAddressException(
            f"After '{ADDR_SCHEME}.', a date specification of the format {date_regex} is expected."
        )

    # Check the entity type
    if entity_type not in ("sensor", "connection", "weather_sensor", "market", "event"):
        raise EntityAddressException(f"Unrecognized entity type: {entity_type}")

    def validate_ea_for_fm_scheme(ea: dict, fm_scheme: str):
        if "fm_scheme" not in ea:
            # Backwards compatibility: assume fm0 if fm_scheme is not specified
            ea["fm_scheme"] = FM0_ADDR_SCHEME
        scheme = ea["scheme"]
        naming_authority = ea["naming_authority"]
        if ea["fm_scheme"] != fm_scheme:
            raise EntityAddressException(
                f"A valid type {fm_scheme[2:]} FlexMeasures entity address starts with '{scheme}.{naming_authority}:{fm_scheme}', please review {entity_address}"
            )

    if fm_scheme == FM1_ADDR_SCHEME:

        # Check the FlexMeasures scheme
        if entity_address.split(":")[1][: len(fm_scheme) + 1] != FM1_ADDR_SCHEME + ".":
            raise EntityAddressException(
                f"A valid type {fm_scheme[2:]} FlexMeasures entity address starts with '{build_ea_scheme_and_naming_authority(get_host())}:{fm_scheme}.', please review {entity_address}"
            )

        match = re.search(
            r"^"
            r"(?P<scheme>.+)\."
            fr"(?P<naming_authority>{date_regex}\.[^:]+)"  # everything until the colon (no port)
            r":"
            r"((?P<fm_scheme>.+)\.)"
            r"(?P<sensor_id>\d+)"
            r"$",
            entity_address,
        )
        if match is None:
            raise EntityAddressException(
                f"Could not parse {entity_type} {entity_address}."
            )
        value_types = {
            "scheme": str,
            "naming_authority": str,
            "fm_scheme": str,
            "sensor_id": int,
        }
    elif fm_scheme != FM0_ADDR_SCHEME:
        raise EntityAddressException(
            f"Unrecognized FlexMeasures scheme for entity addresses: {fm_scheme}"
        )
    elif entity_type == "connection":
        match = re.search(
            r"^"
            r"(?P<scheme>.+)\."
            fr"(?P<naming_authority>{date_regex}\.[^:]+)"  # everything until the colon (no port)
            r":"
            r"((?P<fm_scheme>.+)\.)*"  # for backwards compatibility, missing fm_scheme is interpreted as fm0
            r"((?P<owner_id>\d+):)*"  # owner id is optional
            r"(?P<asset_id>\d+)"
            r"$",
            entity_address,
        )
        if match is None:
            raise EntityAddressException(
                f"Could not parse {entity_type} {entity_address}."
            )
        value_types = {
            "scheme": str,
            "naming_authority": str,
            "owner_id": int,
            "asset_id": int,
        }
    elif entity_type == "weather_sensor":
        match = re.search(
            r"^"
            r"(?P<scheme>.+)"
            r"\."
            fr"(?P<naming_authority>{date_regex}\.[^:]+)"
            r":"
            r"((?P<fm_scheme>.+)\.)*"  # for backwards compatibility, missing fm_scheme is interpreted as fm0
            r"(?=[a-zA-Z])(?P<weather_sensor_type_name>[\w]+)"  # should start with at least one letter
            r":"
            r"(?P<latitude>\-?\d+(\.\d+)?)"
            r":"
            r"(?P<longitude>\-?\d+(\.\d+)?)"
            r"$",
            entity_address,
        )
        if match is None:
            raise EntityAddressException(
                f"Could not parse {entity_type} {entity_address}."
            )
        value_types = {
            "scheme": str,
            "naming_authority": str,
            "weather_sensor_type_name": str,
            "latitude": float,
            "longitude": float,
        }
    elif entity_type == "market":
        match = re.search(
            r"^"
            r"(?P<scheme>.+)"
            r"\."
            fr"(?P<naming_authority>{date_regex}\.[^:]+)"
            r":"
            r"((?P<fm_scheme>.+)\.)*"  # for backwards compatibility, missing fm_scheme is interpreted as fm0
            r"(?=[a-zA-Z])(?P<market_name>[\w]+)"  # should start with at least one letter
            r"$",
            entity_address,
        )
        if match is None:
            raise EntityAddressException(
                f"Could not parse {entity_type} {entity_address}."
            )
        value_types = {"scheme": str, "naming_authority": str, "market_name": str}
    elif entity_type == "event":
        match = re.search(
            r"^"
            r"(?P<scheme>.+)"
            r"\."
            fr"(?P<naming_authority>{date_regex}\.[^:]+)"
            r":"
            r"((?P<fm_scheme>.+)\.)*"  # for backwards compatibility, missing fm_scheme is interpreted as fm0
            r"((?P<owner_id>\d+):)*"  # owner id is optional
            r"(?P<asset_id>\d+)"
            r":"
            r"(?P<event_id>\d+)"
            r":"
            r"(?P<event_type>.+)"
            r"$",
            entity_address,
        )
        if match is None:
            raise EntityAddressException(
                f"Could not parse {entity_type} {entity_address}."
            )
        value_types = {
            "scheme": str,
            "naming_authority": str,
            "owner_id": int,
            "asset_id": int,
            "event_id": int,
            "event_type": str,
        }
    else:
        # Finally, we simply raise without precise information what went wrong
        raise EntityAddressException(f"Could not parse {entity_address}.")

    ea = _typed_regex_results(match, value_types)
    validate_ea_for_fm_scheme(ea, fm_scheme)
    return ea


def build_ea_scheme_and_naming_authority(
    host: str, host_auth_start_month: Optional[str] = None
) -> str:
    """
    This function creates the host identification part of
    USEF's EA1 addressing scheme, so everything but the locally unique string.

    If not given nor configured, host_auth_start_month is the start of the next month for
    localhost.
    """
    domain_parts: TldExtractResult = get_domain_parts(host)

    if host_auth_start_month is None:
        config_var_domain_key = ".".join(
            filter(
                lambda x: x,
                [domain_parts.subdomain, domain_parts.domain, domain_parts.suffix],
            )
        )
        if domain_parts.domain in ("localhost", "127.0.0.1"):
            host_auth_start_month = get_first_day_of_next_month().strftime("%Y-%m")
        elif config_var_domain_key in current_app.config.get(
            "FLEXMEASURES_HOSTS_AND_AUTH_START", {}
        ):
            host_auth_start_month = current_app.config.get(
                "FLEXMEASURES_HOSTS_AND_AUTH_START", {}
            )[config_var_domain_key]
        else:
            raise Exception(
                f"Could not find out when authority for {config_var_domain_key} started. Is FLEXMEASURES_HOSTS_AND_AUTH_START configured for it?"
            )
    regex = r"^\d{4}-\d{2}$"
    if not re.search(regex, host_auth_start_month):
        raise ValueError(
            f"{host_auth_start_month} should adhere to the format {regex}."
        )
    if not int(host_auth_start_month[-2:]) in range(1, 13):
        raise ValueError(
            f"Month in {host_auth_start_month} should be in the range of 1 to 12."
        )

    reversed_domain_name = reverse_domain_name(domain_parts)
    if reversed_domain_name == "":
        raise Exception(f"Could not make domain name from {host}!")
    return f"{ADDR_SCHEME}.{host_auth_start_month}.{reversed_domain_name}"


def reverse_domain_name(domain: Union[str, TldExtractResult]) -> str:
    """
    Returns the reverse notation of the domain.
    You can pass in a string domain or an extraction result from tldextract
    """
    if isinstance(domain, str):
        domain_parts: TldExtractResult = get_domain_parts(domain)
    else:
        domain_parts = domain

    suffix = domain_parts.suffix
    if suffix != "":
        if "." in suffix:
            suffix = ".".join(suffix.split(".")[::-1])
        suffix = f"{suffix}."

    domain = domain_parts.domain

    reversed_subdomain = ""
    if domain_parts.subdomain != "":
        sd_list = ".".join(domain_parts.subdomain.split(".")[::-1])
        reversed_subdomain = f".{sd_list}"

    return f"{suffix}{domain}{reversed_subdomain}"


def get_domain_parts(domain: str) -> TldExtractResult:
    """wrapper for calling tldextract as it logs things about file locks we don't care about."""
    logger = logging.getLogger()
    level = logger.getEffectiveLevel()
    logger.setLevel(logging.ERROR)
    domain_parts: TldExtractResult = tld_extract(domain)
    logging.getLogger().setLevel(level)
    return domain_parts


def _typed_regex_results(match, value_types) -> dict:
    return {
        k: v_type(v) if v is not None else v
        for k, v, v_type in _zip_dic(match.groupdict(), value_types)
    }


def _zip_dic(*dicts):
    for i in set(dicts[0]).intersection(*dicts[1:]):
        yield (i,) + tuple(d[i] for d in dicts)
