"""Build the GitHub Pages copy of the site: ``python -m rutgers_planner.pages --out _site``.

* Home, career outcomes (all majors), compare and sources become static HTML.
* What-if majors and Graduation plan keep their pages; their API calls are answered either by the
  same Python code running in the browser (Pyodide, self-hosted under ``pyodide/``) or by the
  planner on your computer (``python run.py --pages``), picked with a switch on the page.

Nothing personal is published: the build points the What-If record at an empty temporary folder
and packs only files tracked by git (``personal/`` is git-ignored).
"""
