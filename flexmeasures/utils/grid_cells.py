from __future__ import annotations


class LatLngGrid(object):
    """
    Represents a grid in latitude and longitude notation for some rectangular region of interest (ROI).
    The specs are a top-left and a bottom-right coordinate, as well as the number of cells in both directions.
    The class provides two ways of conceptualising cells which nicely cover the grid: square cells and hexagonal cells.
    For both, locations can be computed which represent the corners of said cells.
    Examples:
          - 4 cells in square: 9 unique locations in a 2x2 grid (4*4 locations, of which 7 are covered by another cell)
          - 4 cells in hex: 13 unique locations in a 2x2 grid (4*6 locations, of which 11 are already covered)
          - 10 cells in square: 18 unique locations in a 5x2 grid (10*4 locations, of which 11 are already covered)
          - 10 cells in hex: 34 unique locations in a 5x2 grid (10*6 locations, of which 26 are already covered)
    The top-right and bottom-left locations are always at the center of a cell, unless the grid has 1 row or 1 column.
    In those case, these locations are closer to one side of the cell.
    """

    top_left: tuple[float, float]
    bottom_right: tuple[float, float]
    num_cells_lat: int
    num_cells_lng: int

    def __init__(
        self,
        top_left: tuple[float, float],
        bottom_right: tuple[float, float],
        num_cells_lat: int,
        num_cells_lng: int,
    ):
        self.top_left = top_left
        self.bottom_right = bottom_right
        self.num_cells_lat = num_cells_lat
        self.num_cells_lng = num_cells_lng
        self.cell_size_lat = self.compute_cell_size_lat()
        self.cell_size_lng = self.compute_cell_size_lng()

        # correct top-left and bottom-right if there is only one cell
        if self.num_cells_lat == 1:  # if only one row
            self.top_left = (
                self.top_left[0] + self.cell_size_lat / 4,
                self.top_left[1],
            )
            self.bottom_right = (
                self.bottom_right[0] - self.cell_size_lat / 4,
                self.bottom_right[1],
            )
        if self.num_cells_lng == 1:
            self.top_left = (
                self.top_left[0],
                self.top_left[1] + self.cell_size_lng / 4,
            )
            self.bottom_right = (
                self.bottom_right[0],
                self.bottom_right[1] - self.cell_size_lng / 4,
            )

    def __repr__(self) -> str:
        return (
            f"<LatLngGrid top-left:{self.top_left}, bot-right:{self.bottom_right},"
            + f"num_lat:{self.num_cells_lat}, num_lng:{self.num_cells_lng}>"
        )

    def get_locations(self, method: str) -> list[tuple[float, float]]:
        """Get locations by method ("square" or "hex")"""

        if method == "hex":
            locations = self.locations_hex()
            print(
                "[FLEXMEASURES] Number of locations in hex grid: "
                + str(len(self.locations_hex()))
            )
            return locations
        elif method == "square":
            locations = self.locations_square()
            print(
                "[FLEXMEASURES] Number of locations in square grid: "
                + str(len(self.locations_square()))
            )
            return locations
        else:
            raise Exception(
                "Method must either be 'square' or 'hex'! (is: %s)" % method
            )

    def compute_cell_size_lat(self) -> float:
        """Calculate the step size between latitudes"""
        if self.num_cells_lat != 1:
            return (self.bottom_right[0] - self.top_left[0]) / (self.num_cells_lat - 1)
        else:
            return (self.bottom_right[0] - self.top_left[0]) * 2

    def compute_cell_size_lng(self) -> float:
        """Calculate the step size between longitudes"""
        if self.num_cells_lng != 1:
            return (self.bottom_right[1] - self.top_left[1]) / (self.num_cells_lng - 1)
        else:
            return (self.bottom_right[1] - self.top_left[1]) * 2

    def locations_square(self) -> list[tuple[float, float]]:
        """square pattern"""
        locations = []

        # For each odd cell row, add all the coordinates of the row's cells
        for ilat in range(0, self.num_cells_lat, 2):
            lat = self.top_left[0] + ilat * self.cell_size_lat
            for ilng in range(self.num_cells_lng):
                lng = self.top_left[1] + ilng * self.cell_size_lng
                nw = (
                    lat - self.cell_size_lat / 2,
                    lng - self.cell_size_lng / 2,
                )  # North west coordinate of the cell
                locations.append(nw)
                sw = (
                    lat + self.cell_size_lat / 2,
                    lng - self.cell_size_lng / 2,
                )  # South west coordinate
                locations.append(sw)
            ne = (
                lat - self.cell_size_lat / 2,
                lng + self.cell_size_lng / 2,
            )  # North east coordinate
            locations.append(ne)
            se = (
                lat + self.cell_size_lat / 2,
                lng + self.cell_size_lng / 2,
            )  # South east coordinate
            locations.append(se)

        # In case of an even number of cell rows, add the southern coordinates of the southern most row
        if not self.num_cells_lat % 2:
            lat = self.top_left[0] + (self.num_cells_lat - 1) * self.cell_size_lat
            for ilng in range(self.num_cells_lng):
                lng = self.top_left[1] + ilng * self.cell_size_lng
                sw = (
                    lat + self.cell_size_lat / 2,
                    lng - self.cell_size_lng / 2,
                )  # South west coordinate
                locations.append(sw)
            se = (
                lat + self.cell_size_lat / 2,
                lng + self.cell_size_lng / 2,
            )  # South east coordinate
            locations.append(se)

        return locations

    def locations_hex(self) -> list[tuple[float, float]]:
        """The hexagonal pattern - actually leaves out one cell for every even row."""
        locations = []

        # For each odd cell row, add all the coordinates of the row's cells
        for ilat in range(0, self.num_cells_lat, 2):
            lat = self.top_left[0] + ilat * self.cell_size_lat
            for ilng in range(self.num_cells_lng):
                lng = self.top_left[1] + ilng * self.cell_size_lng
                n = (
                    lat - self.cell_size_lat * 2 / 3,
                    lng,
                )  # North coordinate of the cell
                locations.append(n)
                nw = (
                    lat - self.cell_size_lat * 1 / 4,
                    lng - self.cell_size_lng * 1 / 2,
                )  # North west coordinate
                locations.append(nw)
                s = (lat + self.cell_size_lat * 2 / 3, lng)  # South coordinate
                locations.append(s)
                sw = (
                    lat + self.cell_size_lat * 1 / 4,
                    lng - self.cell_size_lng * 1 / 2,
                )  # South west coordinate
                locations.append(sw)
            ne = (
                lat - self.cell_size_lat * 1 / 4,
                lng + self.cell_size_lng * 1 / 2,
            )  # North east coordinate
            locations.append(ne)
            se = (
                lat + self.cell_size_lat * 1 / 4,
                lng + self.cell_size_lng * 1 / 2,
            )  # South east coordinate
            locations.append(se)

        # In case of an even number of cell rows, add the southern coordinates of the southern most row
        if not self.num_cells_lat % 2:
            lat = self.top_left[0] + (self.num_cells_lat - 1) * self.cell_size_lat
            for ilng in range(
                self.num_cells_lng - 1
            ):  # One less cell in even rows of hexagonal locations
                # Cells are shifted half a cell to the right in even rows of hex locations
                lng = self.top_left[1] + (ilng + 1 / 2) * self.cell_size_lng
                s = (lat + self.cell_size_lat / 3 ** (1 / 2), lng)  # South coordinate
                locations.append(s)
                sw = (
                    lat + self.cell_size_lat / 2,
                    lng - self.cell_size_lat / 3 ** (1 / 2) / 2,
                )  # South west coordinates
                locations.append(sw)
                se = (
                    lat + self.cell_size_lat / 2,
                    lng + self.cell_size_lng / 3 ** (1 / 2) / 2,
                )  # South east coordinates
                locations.append(se)
        return locations


def get_cell_nums(
    tl: tuple[float, float], br: tuple[float, float], num_cells: int = 9
) -> tuple[int, int]:
    """
    Compute the number of cells in both directions, latitude and longitude.
    By default, a square grid with N=9 cells is computed, so 3 by 3.
    For N with non-integer square root, the function will determine a nice cell pattern.
    :param tl: top-left (lat, lng) tuple of ROI
    :param br: bottom-right (lat, lng) tuple of ROI
    :param num_cells: number of cells (9 by default, leading to a 3x3 grid)
    """

    def factors(n):
        """Factors of a number n"""
        return set(
            factor
            for i in range(1, int(n**0.5) + 1)
            if n % i == 0
            for factor in (i, n // i)
        )

    # Find closest integers n1 and n2 that, when multiplied, equal n
    n1 = min(factors(num_cells), key=lambda x: abs(x - num_cells ** (1 / 2)))
    n2 = num_cells // n1

    # Assign largest integer to lat or lng depending on which has the largest spread (earth curvature neglected)
    if br[0] - tl[0] > br[1] - tl[1]:
        return max(n1, n2), min(n1, n2)
    else:
        return min(n1, n2), max(n1, n2)
