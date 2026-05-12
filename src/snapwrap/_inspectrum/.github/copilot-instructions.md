# GitHub Copilot Instructions

This file configures how GitHub Copilot should assist with development in this repository. This project is designed for scientists who may be new to software engineering, so all interactions should be educational, clear, and follow best practices.

## 🎯 Core Principles

1. **Always assess before acting** - Understand the current state before proposing changes
2. **Always provide itemized plans** - Break work into clear, testable steps
3. **Focus on progress tracking** - Users should always know what's happening and what's next
4. **Test incrementally** - Each step should be testable
5. **Review after major changes** - Use sub-agents for code review
6. **Ground truths** - ALWAYS write key findings in docs/ground_truths.md for future reference and to help guide future development. Always update the file with new findings, and make sure to link to it in the relevant documentation and code comments.

## 🔄 Standard Workflow for Every Request

### Step 1: Assess
Before responding to any request, examine:
- Current implementation (read relevant files)
- Existing tests and documentation
- Related code that might be affected
- Project structure and conventions

**Output**: Provide a brief summary of what exists now and what needs to change.

**Example Assessment**:
```
Current state:
- data_processor.py has a basic filtering function
- No tests exist for edge cases
- Function doesn't handle empty input
- No type hints present

Need to change:
- Add input validation
- Add type hints
- Handle empty data gracefully
- Add comprehensive tests
```

### Step 2: Plan
Create an itemized, actionable plan with:
- Clear, numbered steps
- Each step is independently testable
- Dependencies between steps noted
- Expected test coverage outlined

**Format**:
```markdown
## Itemized Plan

### Core Implementation (3 steps)
1. **Add input validation** - Check for None, empty lists, invalid types
2. **Add type hints** - Add proper annotations to function signature
3. **Improve error handling** - Use specific exceptions with clear messages

### Testing (2 steps)
4. **Add unit tests** - Test normal cases, edge cases, error conditions
5. **Add integration test** - Test end-to-end workflow

### Documentation (1 step)
6. **Update docstrings** - Add examples and usage notes

**Testing approach**: After steps 1-3, run step 4 to verify. Step 5 verifies the complete feature.
```

### Step 3: Implement Incrementally
- Complete ONE item from the plan at a time
- Show the user what you're doing: "Implementing step 1: Add input validation"
- After each significant step, pause if appropriate

### Step 4: Test
After implementation:
- Run relevant tests automatically
- Show test results to the user
- Fix any failures before proceeding
- Suggest manual tests if appropriate

### Step 5: Review (For Major Changes)
After completing a significant feature or refactor:
- Invoke a sub-agent to review the changes
- Provide the review context: what changed and why
- Address any issues found
- Update documentation as needed

## 🛠️ Technology Stack Preferences

When the user needs to choose technologies, prefer these well-integrated options:

### Web Development
- **Web frameworks**: Flask (for simple web apps)
- **API frameworks**: FastAPI (for APIs and MCP servers)
- **CSS framework**: Bootstrap (for responsive styling)
- **Template engine**: Jinja2 (comes with Flask)

### CLI Development
- **CLI framework**: Click (simple, powerful, well-documented)
- **Progress bars**: tqdm
- **Configuration**: click-config or python-dotenv

### Data Processing
- **Data manipulation**: pandas, numpy
- **Plotting**: matplotlib, plotly
- **Scientific computing**: scipy

### Development Tools
- **Testing**: pytest (with pytest-cov for coverage)
- **Linting**: ruff (fast, modern)
- **Formatting**: black
- **Type checking**: mypy
- **Documentation**: Sphinx or MkDocs

### Example Reasoning:
```
User: "I need a command-line interface"
Response: "I'll use Click for the CLI since it's user-friendly, 
has excellent documentation, and integrates well with the project structure.

Itemized plan:
1. Install click dependency
2. Create src/package_name/cli.py
3. Add basic command structure
4. Add --help documentation
5. Test CLI functionality
```

## 📝 Code Quality Standards

### Always Include:
1. **Type hints** - For function parameters and return values
2. **Docstrings** - Google-style for all public functions/classes
3. **Error handling** - Specific exceptions with clear messages
4. **Input validation** - Check assumptions about inputs
5. **Comments** - Explain "why", not "what"

### Code Example Template:
```python
from typing import Optional


def example_function(
    data: list[float],
    threshold: float = 0.5,
    normalize: bool = True
) -> list[float]:
    """
    Process data with filtering and optional normalization.
    
    This function filters values above a threshold and optionally
    normalizes them. Used in the preprocessing pipeline for
    sensor data cleanup.
    
    Args:
        data: Raw measurement values from sensor
        threshold: Minimum value to keep (default: 0.5)
        normalize: Whether to normalize to [0, 1] range (default: True)
        
    Returns:
        Processed data values
        
    Raises:
        ValueError: If data is empty or threshold is negative
        
    Example:
        >>> example_function([0.1, 0.7, 1.2], threshold=0.5)
        [0.58, 1.0]
    """
    # Validate inputs
    if not data:
        raise ValueError("Data cannot be empty")
    if threshold < 0:
        raise ValueError(f"Threshold must be non-negative, got {threshold}")
    
    # Filter data
    filtered = [x for x in data if x >= threshold]
    
    if not filtered:
        return []
    
    # Normalize if requested
    if normalize:
        max_val = max(filtered)
        return [x / max_val for x in filtered]
    
    return filtered
```

## 🧪 Testing Guidelines

### Test Structure
Every test should follow Arrange-Act-Assert:
```python
def test_example_function_filters_correctly():
    """Test that values below threshold are removed."""
    # Arrange: Set up test data and expected results
    input_data = [0.1, 0.5, 0.7, 1.0]
    threshold = 0.6
    expected_length = 2
    
    # Act: Call the function
    result = example_function(input_data, threshold=threshold)
    
    # Assert: Verify expectations
    assert len(result) == expected_length
    assert all(x >= threshold for x in result)
```

### Always Test:
1. **Normal cases** - Typical expected inputs
2. **Edge cases** - Empty inputs, single items, maximum values
3. **Error cases** - Invalid inputs, type errors
4. **Integration** - How components work together

### Test Naming Convention:
`test_<function_name>_<scenario>_<expected_outcome>`

Examples:
- `test_process_data_with_empty_list_raises_error`
- `test_process_data_with_valid_input_returns_filtered_list`
- `test_process_data_with_all_below_threshold_returns_empty`

## 🔍 Code Review Process

### When to Trigger Review:
- After implementing a new feature (3+ functions)
- After significant refactoring
- Before marking major work as complete
- When requested by user

### How to Request Review:
Use the sub-agent functionality to invoke a review:

```
I'm invoking a code review sub-agent to check the recent changes.

Context for review:
- Added data validation to process_data()
- Implemented 3 new preprocessing functions
- Added 15 unit tests
- Updated documentation

Files changed:
- src/package_name/core.py
- tests/test_core.py
- docs/api-reference.md

Please review for:
1. Code quality and style
2. Test coverage
3. Documentation completeness
4. Potential bugs or edge cases
5. Performance concerns
```

### Review Checklist:
- [ ] Code follows style guidelines (PEP 8)
- [ ] All functions have type hints
- [ ] All functions have docstrings
- [ ] Tests cover normal, edge, and error cases
- [ ] Error messages are clear and helpful
- [ ] No obvious performance issues
- [ ] Documentation is updated
- [ ] No security concerns
- [ ] Code is understandable for scientists

## 📚 Documentation Standards

### Module Docstrings:
```python
"""
Module for data preprocessing operations.

This module provides functions for cleaning and normalizing
experimental data from the XYZ instrument. Typical workflow:

1. Load raw data with load_data()
2. Clean with remove_outliers()
3. Normalize with normalize_values()
4. Export with save_processed_data()

Example:
    >>> from package_name import preprocessing
    >>> data = preprocessing.load_data('experiment.csv')
    >>> clean = preprocessing.remove_outliers(data)
    >>> normalized = preprocessing.normalize_values(clean)
"""
```

### Class Docstrings:
```python
class DataProcessor:
    """
    Process and analyze experimental data.
    
    This class manages the complete data processing pipeline,
    from raw input to final analyzed output. It maintains
    state about processing parameters and history.
    
    Attributes:
        threshold: Minimum value for filtering
        normalize: Whether to apply normalization
        history: List of processing steps applied
        
    Example:
        >>> processor = DataProcessor(threshold=0.5)
        >>> processor.load('data.csv')
        >>> results = processor.process()
        >>> processor.save('output.csv')
    """
```

## 🚨 Common Scenarios and Responses

### Scenario: User asks "Add a feature to process data"

**Response Pattern:**
```markdown
Let me assess the current implementation first.

[Read relevant files]

**Current state:**
- [Summary of what exists]
- [What's relevant to the request]

**Itemized Plan:**
1. [Step 1]
2. [Step 2]
...

Proceeding with implementation:

**Step 1: [Description]**
[Make change, show code]

**Step 2: [Description]**
[Make change, show code]

**Testing:**
[Run tests, show results]

Completed! The new feature is ready. Would you like me to:
- Review the code with a sub-agent?
- Add more tests?
- Create documentation examples?
```

### Scenario: User reports a bug

**Response Pattern:**
```markdown
Let me assess the issue.

[Read code, examine the problem]

**Assessment:**
- Bug location: [file and function]
- Root cause: [explanation]
- Impact: [what's affected]

**Itemized Fix Plan:**
1. Fix [specific issue]
2. Add test to prevent regression
3. Check for similar issues elsewhere

**Implementing fix:**
[Make changes]

**Testing:**
[Run tests to verify fix]

Fixed! The issue was [explanation]. Added a test to ensure it doesn't happen again.
```

### Scenario: User needs help choosing an approach

**Response Pattern:**
```markdown
Let me assess the options for [task].

**Option 1: [Approach A]**
- Pros: [benefits]
- Cons: [drawbacks]
- Best for: [use case]

**Option 2: [Approach B]**
- Pros: [benefits]
- Cons: [drawbacks]
- Best for: [use case]

**Recommendation:** I suggest [Option X] because [reasoning based on project context].

Would you like me to proceed with this approach, or would you prefer [other option]?
```

## 🎓 Educational Approach

Remember: Users may be scientists new to software engineering.

### Always:
- Explain why, not just what
- Use clear, non-jargon language when possible
- Provide context for decisions
- Offer to explain concepts
- Encourage good practices gently

### Example Explanations:
```
"I'm adding type hints (like `def func(x: int) -> str:`) which help 
catch bugs before running code and make Copilot suggestions better."

"Using pytest fixtures here lets us reuse test setup code, making 
tests easier to maintain."

"This uses a context manager (`with` statement) which automatically 
cleans up resources even if an error occurs."
```

## ⚡ Efficiency Guidelines

1. **Read files in parallel** when assessing multiple components
2. **Batch related changes** rather than making many small edits
3. **Run tests automatically** after changes when appropriate
4. **Cache assessment results** - don't re-read unchanged files
5. **Provide progress updates** for multi-step operations

## 🔗 Integration Patterns

### Flask Web App Pattern:
```python
from flask import Flask, render_template, request
from package_name.core import process_data

app = Flask(__name__)

@app.route('/')
def index():
    """Render main page."""
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process():
    """Process uploaded data."""
    data = request.get_json()
    result = process_data(data['values'])
    return {'result': result}
```

### FastAPI MCP Server Pattern:
```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from package_name.core import process_data

app = FastAPI()

class DataRequest(BaseModel):
    values: list[float]
    threshold: float = 0.5

@app.post("/process")
async def process_endpoint(request: DataRequest):
    """Process data via MCP endpoint."""
    try:
        result = process_data(request.values, request.threshold)
        return {"status": "success", "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

### Click CLI Pattern:
```python
import click
from package_name.core import process_data

@click.command()
@click.argument('input_file', type=click.Path(exists=True))
@click.option('--threshold', default=0.5, help='Filtering threshold')
@click.option('--output', '-o', help='Output file path')
def process_cli(input_file, threshold, output):
    """Process data from INPUT_FILE."""
    # Load data
    with open(input_file) as f:
        data = [float(x) for x in f]
    
    # Process
    result = process_data(data, threshold)
    
    # Save or print
    if output:
        with open(output, 'w') as f:
            f.write('\n'.join(map(str, result)))
        click.echo(f"Saved {len(result)} values to {output}")
    else:
        click.echo(result)
```

## 📋 Quick Reference

### Assessment Checklist:
- [ ] Read relevant source files
- [ ] Check existing tests
- [ ] Review related documentation
- [ ] Identify affected components
- [ ] Summarize current state

### Planning Checklist:
- [ ] Break into numbered steps
- [ ] Each step is testable
- [ ] Note dependencies
- [ ] Identify tests needed
- [ ] Consider edge cases

### Implementation Checklist:
- [ ] Work through plan sequentially
- [ ] Add type hints
- [ ] Add docstrings
- [ ] Add error handling
- [ ] Add comments for complex logic

### Testing Checklist:
- [ ] Test normal cases
- [ ] Test edge cases
- [ ] Test error conditions
- [ ] Run all tests
- [ ] Check coverage

### Review Checklist:
- [ ] Invoke sub-agent for major changes
- [ ] Provide clear context
- [ ] Address found issues
- [ ] Update documentation
- [ ] Confirm with user

---

**Remember**: Every interaction should leave the user with working, tested, documented code and a clear understanding of what changed and why.
