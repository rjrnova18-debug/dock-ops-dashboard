# Dock Ops Dashboard

A live operations board for the loading area of a distribution center, built with Django.
It follows every transport through its visit (appointment, arrival, inspection, loading,
departure) and measures how closely the day follows the plan.

> **Status: work in progress.** The live board works end to end; the simulator, the
> history page and deployment are being built in phases (see [Roadmap](#roadmap).

## Features

- **Live board** (public, made for a wall display): weekly dispatch counter, a status
  pipeline, loading and cycle time trends, adherence per checkpoint, hangar-style bay
  cards with live loading timers, and the incoming list. It refreshes itself every 30 s
  without reloading; any chart, the week's completed list and every transport open in
  a detail view, by mouse or keyboard. On a wide screen it is a fixed 1920×1080 "wall"
  layout scaled to fit; on smaller screens the panels stack.
- **History** *(planned)* (sign-in required): indicators for any period, grouped by day, week or
  month, an activity calendar, slowest and fastest loadings, and CSV / Excel downloads.
- **Working time, not clock time**: durations skip nights, breaks, the weekly rest day
  and the public holidays of a configurable country (150+ countries, via the
  [`holidays`](https://pypi.org/project/holidays/) package).
- **Demo data**: a seed command builds months of invented history and a "today" that
  shows every state of the board at any hour; a simulator moves it forward step by step
  (`python manage.py simulate`, a button in the admin, or automatically while the board
  is open).
- **Ready for translation**: every visible text goes through Django's translation
  system, in templates and in JavaScript. English only for now.

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
python manage.py runserver          # board at http://127.0.0.1:8000/, admin at /admin/ (createsuperuser first)
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
| `BOARD_REFRESH_SECONDS` | `30` | How often the live board asks for fresh data |
| `SIMULATOR_AUTO` | `0` | `1` to let the demo operation advance by itself every 1-2 minutes while the board is open |

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
├── board/           Live board app: Transport model, demo data, views, page and JS
│   ├── demo.py      Invented data as pure functions (seed)
│   ├── conf.py      The operation's configuration and public holidays
│   └── static/board/  board.js, charts.js, overlays.js (ES modules, no build step)
├── templates/       Shared templates (base.html)
├── static/          Shared CSS and JS, vendored fonts and Chart.js (with licenses)
├── manage.py
├── pyproject.toml   pytest configuration
└── requirements.txt
```

## Roadmap

- [x] Domain rules (`dockops`) with tests
- [x] Project setup
- [x] Live board: model, seed data, JSON endpoint, page, charts and overlays
- [x] Public holidays as days off
- [x] Simulator (manual and automatic) and admin
- [ ] History page with sign-in, permissions and downloads
- [ ] PostgreSQL
- [ ] Polish, CI and deployment

## What I learned

To be written as the project grows.
