# Contributing to CloudHorus

Thank you for your interest in contributing to CloudHorus! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Coding Standards](#coding-standards)
- [Submitting Changes](#submitting-changes)
- [Reporting Issues](#reporting-issues)

## Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/CloudHorus.git`
3. Create a feature branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Submit a pull request

## Development Setup

### Prerequisites

- **Python 3.10+**
- **Graphviz** system package (`sudo apt install graphviz` / `brew install graphviz`)
- **Azure CLI** (only for Live Mode — scanning real Azure subscriptions)

### Installation

```bash
# Clone the repository
git clone https://github.com/CloudHorus/CloudHorus.git
cd CloudHorus

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install with dev dependencies
make install-dev
# Or manually:
pip install -e ".[dev]"
```

### Quick Commands

```bash
make help          # Show all available commands
make test          # Run tests
make test-cov      # Run tests with coverage
make lint          # Run linters (black, isort, mypy)
make format        # Auto-format code
make clean         # Remove build artifacts
make run ARGS="--help"  # Run CLI
make run-gui       # Launch desktop GUI
```

### Running Tests

```bash
# Run all tests
make test

# Run specific test file
python3 -m pytest tests/test_flag_combinations.py -v

# Run with coverage
make test-cov
```

## Project Structure

```
CloudHorus/
├── src/
│   ├── main.py              # CLI entry point
│   ├── version.py            # Single version source
│   ├── core/                 # Core engine (graph generation, Azure CLI, Bicep)
│   │   ├── azure_cli.py      #   Azure resource fetching & template export
│   │   ├── bicep_builder.py  #   Bicep → ARM template compilation
│   │   ├── graph_generator.py #  Graphviz DOT graph generation
│   │   └── resource_processor.py # Resource & dependency processing
│   ├── utils/                # Shared utilities
│   │   ├── geticons.py       #   Azure icon resolver
│   │   ├── graph_utils.py    #   Graph helper functions
│   │   ├── logger.py         #   Logging setup
│   │   ├── skip_patterns.py  #   Resource type filters
│   │   └── windows_encoding.py # Windows console encoding
│   └── cloudhorus/           # Service-oriented architecture layer
│       ├── models/           #   Data models & configuration
│       ├── services/         #   Business logic services
│       ├── exporters/        #   PNG, DOT, Draw.io exporters
│       ├── config/           #   Configuration management
│       └── utils/            #   Package-level utilities
├── tests/                    # Pytest test suite
│   ├── conftest.py           #   Shared fixtures & mock infrastructure
│   └── mock_templates/       #   Template factories for tests
├── webui/                    # HTML/CSS/JS frontend for desktop GUI
├── icons/                    # Azure resource icon set (PNG)
├── samples/                  # Example Bicep templates & parameters
├── scripts/                  # Helper shell scripts
├── docs/                     # Documentation
└── examples/                 # Usage examples
```

## Coding Standards

### Python Style Guide

- Follow PEP 8
- Use type hints for all functions
- Maximum line length: 120 characters
- Use docstrings (Google style) for all public functions and classes

### Example

```python
from typing import List, Optional

def process_resources(
    resource_ids: List[str],
    subscription_id: str,
    optimize: bool = True
) -> Optional[dict]:
    """Process Azure resources and return metadata.

    Args:
        resource_ids: List of Azure resource IDs to process
        subscription_id: Azure subscription ID
        optimize: Whether to apply optimizations

    Returns:
        Dictionary containing processed resource metadata, or None if processing fails

    Raises:
        ValueError: If resource_ids is empty
        AzureError: If Azure API call fails
    """
    if not resource_ids:
        raise ValueError("resource_ids cannot be empty")

    # Implementation here
    pass
```

### Commit Messages

Use conventional commits format:

```
type(scope): subject

body

footer
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

Example:
```
feat(azure): add support for Azure Container Apps

Added AzureContainerAppsService to handle container app resources.
Includes resource discovery and visualization.

Closes #123
```

## Submitting Changes

### Pull Request Process

1. **Update Documentation**: Ensure all documentation is updated
2. **Add Tests**: Include tests for new functionality
3. **Run Tests**: Ensure all tests pass
4. **Code Quality**: Run linting and formatting tools
5. **Update CHANGELOG**: Add entry describing your changes
6. **Create PR**: Submit pull request with clear description

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] All tests pass
- [ ] Added new tests
- [ ] Manual testing completed

## Checklist
- [ ] Code follows project style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] Documentation updated
- [ ] No new warnings generated
```

## Reporting Issues

### Bug Reports

Include:
- Clear, descriptive title
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, Azure CLI version)
- Error messages and logs
- Screenshots if applicable

### Feature Requests

Include:
- Clear description of the feature
- Use case and motivation
- Proposed implementation (if any)
- Alternative solutions considered

## Architecture Guidelines

### Adding New Services

1. Create service class in `src/cloudhorus/services/`
2. Inherit from base service if applicable
3. Add comprehensive docstrings
4. Include type hints
5. Add unit tests in `tests/`
6. Update `__init__.py` exports

### Adding New Models

1. Create model in `src/cloudhorus/models/`
2. Use `@dataclass` decorator
3. Include type hints for all fields
4. Add validation in `__post_init__` if needed
5. Add unit tests in `tests/`

### Adding New Utilities

1. Create utility in `src/cloudhorus/utils/` or `src/utils/`
2. Keep functions focused and reusable
3. Add comprehensive docstrings
4. Include type hints
5. Add unit tests in `tests/`

## Questions?

- Open an issue for questions
- Check existing documentation in `docs/`
- Review examples in `examples/`

Thank you for contributing to CloudHorus! 🦅

