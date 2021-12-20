def determine_flow_unit(stock_unit: str, time_unit: str = "h"):
    """For example:
    >>> determine_flow_unit("m3")  # m3/h
    >>> determine_flow_unit("kWh")  # kW
    """
    return (
        stock_unit.rpartition(time_unit)[0]
        if stock_unit.endswith(time_unit)
        else f"{stock_unit}/{time_unit}"
    )


def determine_stock_unit(flow_unit: str, time_unit: str = "h"):
    """For example:
    >>> determine_stock_unit("m3/h")  # m3
    >>> determine_stock_unit("kW")  # kWh
    """
    return (
        flow_unit.rpartition(f"/{time_unit}")[0]
        if flow_unit.endswith(f"/{time_unit}")
        else f"{flow_unit}{time_unit}"
    )


def is_power_unit(unit: str) -> bool:
    """For example:
    >>> is_power_unit("kWh")  # True
    >>> is_power_unit("°C")  # False
    >>> is_power_unit("EUR/kWh")  # True
    """
    return unit in ("W", "Wh", "kW", "kWh", "MW", "MWh")
