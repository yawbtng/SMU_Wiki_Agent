## ADDED Requirements

### Requirement: Default operator UI is React and FastAPI only
The repository SHALL NOT require Streamlit for operator workflows.

#### Scenario: Quickstart
- **WHEN** an operator follows README quickstart
- **THEN** instructions SHALL start `./start.sh` and open port 5173
- **AND** SHALL NOT require `streamlit run app.py`

#### Scenario: Python dependencies
- **WHEN** `pip install -r requirements.txt` completes
- **THEN** `streamlit` SHALL NOT be installed

#### Scenario: Navigation contract
- **WHEN** `GET /api/navigation` is called
- **THEN** response SHALL include workflow tabs from `app.navigation.WORKFLOW_TABS`

### Requirement: No Streamlit imports in product code
Product packages SHALL NOT import Streamlit.

#### Scenario: Source scan
- **WHEN** static analysis runs over `src/scrape_planner/`
- **THEN** no module SHALL contain `import streamlit`
