# Dock Ops Dashboard

A live operations board for the loading area of a distribution center, built with Django.
It follows every transport through its visit (appointment, arrival, inspection, loading,
departure) and measures how closely the day follows the plan.

> **Status: work in progress.** The domain rules are done and tested; the web
> application is being built in phases (see [Roadmap](#roadmap)).

## Features

Planned for v1.0:

- **Live board** (public, made for a wall display): weekly dispatch counter, a status
  pipeline, loading and cycle time trends, adherence per checkpoint, hangar-style bay
  cards with live loading timers, and the incoming list. Refreshes itself every 30 s.
- **History** (sign-in required): indicators for any period, grouped by day, week or
  month, an activity calendar, slowest and fastest loadings, and CSV / Excel downloads.
- **Working time, not clock time**: durations skip nights, breaks, the weekly rest day
  and the public holidays of a configurable country (150+ countries, via the
  [`holidays`](https://pypi.org/project/holidays/) package).
- **Demo data**: a seed command and a simulator that moves the operation forward, so
  the board always looks like a day in progress. All data is invented.

## Tech stack

Python 3.12 · Django 5.2 LTS · SQLite (PostgreSQL later) · Django templates + plain
JavaScript · Chart.js · pytest + pytest-django

## Architecture

The business rules live in `dockops`, a plain Python package with no Django in it.
Django stores the data, serves the pages and hands lists of transports to `dockops`.

```
 Browser ──HTTP──▶ Django (config/ + apps) ──ORM──▶ Database
                        │   ▲
            dataclasses │   │ JSON-ready dicts
                        ▼   │
                     dockops/  (pure Python: models, rules, live, history)
```

A test enforces that `dockops` never imports Django, so the rules stay testable in
milliseconds and independent of the framework.

## Run it locally

```bash
python -m venv venv
source venv/Scripts/activate      # Windows (Git Bash); on macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # invented data around the current time (--seed N to repeat it)
python manage.py runserver
```

### Configuration

All settings have development defaults. For a deployment, set:

| Variable | Default | Meaning |
|---|---|---|
| `DJANGO_SECRET_KEY` | a development value | Required when debug is off |
| `DJANGO_DEBUG` | `1` | `0` to turn debug off |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names |
| `TIME_ZONE` | `UTC` | The operation's local time zone |
| `HOLIDAYS_COUNTRY` | empty (no holidays) | ISO country code, e.g. `US`, `DE`. Public holidays count as days off |
| `HOLIDAYS_SUBDIVISION` | empty | State or province, for countries with regional holidays |

## Run the tests

```bash
python -m pytest
```

## Project structure

```
dock-ops-dashboard/
├── config/          Django project: settings, root URLs, WSGI/ASGI
├── dockops/         Domain rules in pure Python (no Django)
│   └── tests/       One test file per module
├── manage.py
├── pyproject.toml   pytest configuration
└── requirements.txt
```

## Roadmap

- [x] Domain rules (`dockops`) with tests
- [x] Project setup
- [ ] Live board: model, seed data, JSON endpoint, page and charts
- [ ] Simulator and admin
- [ ] History page with sign-in, permissions and downloads
- [ ] PostgreSQL
- [ ] Polish, CI and deployment

## What I learned

To be written as the project grows.
