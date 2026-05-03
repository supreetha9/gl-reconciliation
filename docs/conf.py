"""Sphinx configuration for the GL Reconciliation documentation."""

from __future__ import annotations

import os
import sys
from datetime import datetime

# Make `data_generator` importable for autodoc.
sys.path.insert(0, os.path.abspath(".."))


# ---------------------------------------------------------------------------
# Project information
# ---------------------------------------------------------------------------

project = "Daily GL Reconciliation"
author = "Vijaya Supreetha Gurrala"
copyright = f"{datetime.now().year}, {author}"

try:
    from importlib.metadata import version as _version

    release = _version("gl-reconciliation")
except Exception:
    release = "0.1.0"

version = release


# ---------------------------------------------------------------------------
# General configuration
# ---------------------------------------------------------------------------

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "sphinxcontrib.mermaid",
]

source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# Treat warnings as errors only in CI; locally we want best-effort builds.
nitpicky = False


# ---------------------------------------------------------------------------
# MyST (Markdown) configuration
# ---------------------------------------------------------------------------

myst_enable_extensions = [
    "colon_fence",      # ::: admonitions
    "deflist",          # definition lists
    "tasklist",         # GitHub-style checkboxes
    "linkify",          # bare URLs become clickable links
    "attrs_inline",     # inline attributes on text/images
    "fieldlist",        # field lists in markdown
    "substitution",     # |key| -> value substitutions
    "smartquotes",
]

myst_heading_anchors = 3
myst_substitutions = {
    "project_version": release,
    "python_version": "3.13",
    "dbt_version": "1.11",
    "postgres_version": "16",
}


# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------

html_theme = "furo"
html_title = "Daily GL Reconciliation"
html_short_title = "GL Recon"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_show_sourcelink = False
html_show_sphinx = False
html_copy_source = False

html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
    "top_of_page_buttons": ["view", "edit"],
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/supreetha9/gl-reconciliation",
            "html": (
                '<svg stroke="currentColor" fill="currentColor" stroke-width="0" '
                'viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">'
                '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 '
                '0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-'
                '.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-'
                '1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 '
                '0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-'
                '.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25'
                '.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0'
                '-4.42-3.58-8-8-8z"></path></svg>'
            ),
            "class": "",
        },
    ],
    "source_repository": "https://github.com/supreetha9/gl-reconciliation/",
    "source_branch": "main",
    "source_directory": "docs/",
}


# ---------------------------------------------------------------------------
# Extensions configuration
# ---------------------------------------------------------------------------

# autodoc / napoleon
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "member-order": "bysource",
}
autodoc_typehints = "description"
autodoc_typehints_format = "short"
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False

# intersphinx
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

# sphinx-copybutton -- strip prompt characters when copying shell snippets
copybutton_prompt_text = r">>> |\.\.\. |\$ |# |% |In \[\d*\]: "
copybutton_prompt_is_regexp = True
copybutton_only_copy_prompt_lines = False

# sphinxcontrib-mermaid
mermaid_version = "10.9.0"
mermaid_init_js = "mermaid.initialize({startOnLoad:true, theme:'default', securityLevel:'loose'});"
