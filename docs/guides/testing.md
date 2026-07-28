# Testing Guide

## Running Tests

    (project-specific test command)

## Test Organization

- Tests live in `tests/` (or alongside source, depending on language)
- Name test files to mirror source files
- One test file per module

## Test Conventions

- Use descriptive test names that explain the expected behavior
- Follow Arrange-Act-Assert pattern
- Keep tests independent — no shared mutable state
- Mock external dependencies, not internal logic
