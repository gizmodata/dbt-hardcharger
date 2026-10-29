"""A stand-in for the user's browser in the browser sign-in tests, run by the driver with the
sign-in URL as its last argument. It opens the URL and follows the identity provider's
redirect back to the server's callback (on the server's own port, Chargewire §4.3), as a browser
does after the user signs in. The argument before the URL is the code
the mock identity provider hands out ("code-ok..." it then accepts, anything else it refuses).
(Not an environment variable: the Go runtime in the driver library keeps the environment it
started with.) An argument before the code, when given, names a file that gets one line per
sign-in.

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


class ToLoopback(urllib.request.HTTPRedirectHandler):
    """Follows a redirect to localhost at 127.0.0.1 (the server's default redirect URI names
    localhost, which may resolve to ::1 first)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = newurl.replace("://localhost:", "://127.0.0.1:")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


separator = "&" if urllib.parse.urlsplit(url=auth_url).query else "?"
url = auth_url + separator + urllib.parse.urlencode(query={"mock_code": sys.argv[-2]})
# A server with TLS has the test CA's certificate: like a user clicking through a browser
# warning, the stand-in doesn't verify it (the driver verifies the server it talks to).
context = ssl.create_default_context()
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE
opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), ToLoopback())
with opener.open(url.replace("://localhost:", "://127.0.0.1:"), timeout=10) as response:
    response.read()
