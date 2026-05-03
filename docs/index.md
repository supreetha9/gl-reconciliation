# Daily General Ledger Reconciliation

**Reconciliation-as-code for finance.**

A daily, automated pipeline that proves AP, AR, and Inventory sub-ledgers tie out to the General Ledger — modeled on the controls a Big-4-audited finance team would actually ship in production.

This documentation is the canonical reference for engineers and analysts working on the project. It covers what the system does, how it is architected, how to set it up locally, and how to extend it with new reconciliation checks.

---

## At a glance

| | |
|---|---|
| **Domain**       | Finance / Accounting (General Ledger reconciliation)                                                                                          |
| **Pattern**      | Reconciliation-as-code: declarative tolerance rules, dbt-driven models, immutable audit trail                                                  |
| **Core stack**   | PostgreSQL {{ postgres_version }}, dbt-core {{ dbt_version }}, Python {{ python_version }}                                                     |
| **Data volume**  | ~50K sub-ledger postings + ~100K GL journal lines per 30-day window                                                                            |
| **Recon checks** | 9 dbt-modelled checks: control account, transaction-level matching, roll-forward, variance, aging, FX revaluation, suspense, manual-JE, summary |
| **Orchestration**| Dagster (software-defined assets, daily 08:00 PT schedule, freshness asset checks)                                                              |
| **Cockpit**      | Streamlit 4-page app: Recon Scorecard, Break Detail, Aging Report, Auditor Evidence (Excel pack export)                                          |
| **Repository**   | [github.com/supreetha9/gl-reconciliation](https://github.com/supreetha9/gl-reconciliation)                                                      |

---

## Where to start

- **New to the project?** Begin with [Getting Started](getting_started.md). It walks through installing the toolchain, spinning up Postgres in Docker, generating synthetic data, and running your first `dbt build`. Full setup takes about ten minutes.
- **Want to understand how it works?** Read [Architecture](architecture.md). It covers the medallion layers, the sub-ledger → GL data flow, and the design decisions behind the recon engine.
- **Building a new reconciliation check?** Jump to [Reconciliation Engine](reconciliation_engine.md). Each of the nine checks is documented, plus the tolerance and materiality model.
- **Working on the codebase?** [Development](development.md) covers the local dev workflow, testing conventions, and a cookbook for adding a new check end-to-end.

---

## Documentation map

```{toctree}
:maxdepth: 2
:caption: User Guide

getting_started
architecture
data_model
reconciliation_engine
```

```{toctree}
:maxdepth: 2
:caption: Components

data_generator
dbt_project
orchestration
recon_cockpit
```

```{toctree}
:maxdepth: 2
:caption: Developer Guide

development
troubleshooting
```

```{toctree}
:maxdepth: 1
:caption: Reference

reference/cli
reference/makefile
reference/configuration
```
