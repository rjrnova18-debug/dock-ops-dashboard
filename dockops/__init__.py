"""dockops: framework-free rules for a distribution center dock operations dashboard.

Modules:
    models   the data: Transport, its enums and the operation's configuration
    rules    the business rules, as pure functions over those models
    live     the live board: one JSON-ready dict built from a list of transports
    history  the history page: indicators of any past period, and the download rows
"""
