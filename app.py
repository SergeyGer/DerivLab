"""DerivLab Streamlit entry point."""

from __future__ import annotations

import sys

import streamlit as st

# Streamlit Community Cloud cannot change Python after deployment. Fail with a
# useful message instead of a redacted ModuleNotFoundError if an old app was
# created before the Python 3.11 minimum.
if sys.version_info < (3, 11):  # noqa: UP036 - intentional old-runtime diagnostic
    st.set_page_config(
        page_title="DerivLab · Python 3.11 required",
        page_icon="⚠️",
        layout="wide",
    )
    st.error(
        "DerivLab requires Python 3.11 or newer. This Streamlit Cloud app was "
        "created with an older Python, and Community Cloud cannot change Python "
        "in place. Delete the app and redeploy it with Python 3.11 or 3.12."
    )
    st.code(
        f"Detected Python {sys.version.split()[0]}. "
        "In Streamlit Cloud: Manage app → Delete app, then deploy again with "
        "Advanced settings → Python 3.11."
    )
    st.stop()

from derivlab.ui import main  # noqa: E402

main()
