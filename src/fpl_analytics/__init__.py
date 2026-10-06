"""FPL Analytics — weekly Fantasy Premier League data pipeline.

Modules
-------
fetch     : pulls raw data from the official FPL API
clean     : normalizes raw JSON into tidy pandas DataFrames
metrics   : value-pick analytics (points per million, form, etc.)
squad     : tracks a specific manager's team performance over the season
pipeline  : orchestrates fetch -> clean -> analyze -> export
"""

__version__ = "0.1.0"
