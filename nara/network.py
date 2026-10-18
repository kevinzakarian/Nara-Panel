"""HTTPS-only redirects for fixed upstream release downloads."""
from urllib import request
from urllib.parse import urlsplit


class HTTPSRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != 'https':
            raise ValueError('Release redirects must use HTTPS')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_https(value, timeout):
    url=value.full_url if isinstance(value,request.Request) else value
    if urlsplit(url).scheme != 'https':
        raise ValueError('An HTTPS release is required')
    return request.build_opener(HTTPSRedirect()).open(value, timeout=timeout)
