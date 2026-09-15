# supplier-price-monitoring-is

Educational information system for monitoring material prices across suppliers.
Developed as an individual project for the course "Інформаційні системи" (KPI, IASA)
using spec-driven development with a coding agent.

The system concept and requirements live in `/spec`; that directory is the single source of truth.

## Data refresh

The source of prices is the suppliers' price lists.
Prices are refreshed from these price lists automatically on a daily schedule.
Price comparisons are not precomputed: they are built on request, at the moment a user views them.
This follows the "Коли" (when) section of `spec/concept.md`.
