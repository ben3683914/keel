# Fixture Conventions

Shared fixture corpus for unit and integration tests.

- Layout: `tests/fixtures/<area>/<case>/` holds an `input/` state tree plus expected
  outputs (`findings.json`, `repaired/`, or rendered artifacts).
- Validator fixtures are named by V-rule, e.g. `fixtures/validator/v06-category-prefix-mismatch/`.
- Every repair fixture gets an automatic idempotence assertion: a second pass over the
  repaired output must find nothing (Article 002).
- Unit tests mirror `src/` one-to-one: `src/<module>/<file>.ts` ↔ `tests/unit/<module>/<file>.test.ts`.
