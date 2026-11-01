"""
Checks that the dashboard page's inline script parses, since one syntax
error there silently breaks every button. Needs node. Run from the repo
root: python scripts/ci/check_dashboard_js.py
"""
import pathlib
import subprocess
import sys
import tempfile

page = pathlib.Path("environment/frontend_server/templates/dashboard/dashboard.html").read_text()
js = page[page.rindex("<script>") + len("<script>"):page.rindex("</script>")]
# The script contains two Django template tags; give them plain JS values.
js = (js.replace("{% static 'assets/characters/profile/' %}", "/static/")
        .replace("{{ histories_json|safe }}", "[]"))
if "{%" in js or "{{" in js:
  sys.exit("The dashboard script has a Django template tag this check doesn't "
           "know about; add a replacement for it in scripts/ci/check_dashboard_js.py")
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
  fh.write(js)
result = subprocess.run(["node", "--check", fh.name])
print("Dashboard script parses" if result.returncode == 0 else "Dashboard script has a syntax error")
sys.exit(result.returncode)
