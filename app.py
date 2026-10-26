r"""PrintProof AI — entry point.

Two tools in one app:
  * Excel Print Optimizer (first, the main tool): turns a large Excel worksheet into a concise, verified,
    print-ready PDF. Deterministic Python + Microsoft Excel (Windows) + measurements of the real PDF.
  * PDF Checker (second): checks an existing PDF against page, paper, font and margin requirements,
    with an optional PydanticAI agent (gpt-6-luna via Portkey) that reads requirements written in English.

Run:  .\.venv\Scripts\python.exe -m streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="PrintProof AI", page_icon="🖨️", layout="wide")

navigation = st.navigation(
    [
        st.Page("pages/excel_print_optimizer.py", title="Excel Print Optimizer", icon="📊", default=True),
        st.Page("pages/pdf_checker.py", title="PDF Checker", icon="🖨️"),
    ],
    position="hidden",   # each page shows its own, clearly labelled links to both tools
)
navigation.run()
