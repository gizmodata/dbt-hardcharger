"""A stand-in for the user's browser in the browser sign-in tests, run by the driver with the
sign-in URL as its last argument: the identity provider "sends it back" to the server's
callback (the auth URL's redirect_uri) with the code given as the argument before it. (Not an
environment variable: the Go runtime in the driver library keeps the environment it started
with.) An argument before the code, when given, names a file that gets one line per sign-in.

    python fake_browser.py [SIGN_IN_LOG] CODE URL
"""

import ssl
import sys
import urllib.parse
import urllib.request

auth_url = sys.argv[-1]
if len(sys.argv) > 3:
    with open(file=sys.argv[-3], mode="a") as sign_in_log:
        sign_in_log.write("sign-in\n")
params = urllib.parse.parse_qs(qs=urllib.parse.urlsplit(url=auth_url).query)
callback = params["redirect_uri"][0].replace("://localhost:", "://127.0.0.1:")
query = urllib.parse.urlencode(query={"code": sys.argv[-2], "state": params["state"][0]})
# A sign-in server with TLS has the test CA's certificate: like a user clicking through a
# browser warning, the stand-in doesn't verify it (the driver verifies the server it talks to).
context = ssl.create_default_context()
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE
with urllib.request.urlopen(url=f"{callback}?{query}", timeout=10, context=context) as response:
    response.read()
