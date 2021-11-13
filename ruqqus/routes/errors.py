from ruqqus.helpers.wrappers import *
from ruqqus.helpers.session import *
from ruqqus.classes.custom_errors import *
from flask import *
from urllib.parse import quote, urlencode
import time
from ruqqus.__main__ import app, r, cache
import gevent

# Errors


def error_wrapper(f):

    def wrapper(*args, **kwargs):

        resp=make_response(f(*args, **kwargs))
        g.db.rollback()
        g.db.close()
        return resp

    wrapper.__name__=f.__name__
    return wrapper


@app.errorhandler(401)
@error_wrapper
def error_401(e):

    return {"error": "401 Not Authorized"}, 401


@app.errorhandler(PaymentRequired)
@error_wrapper
@auth_desired
@api()
def error_402(e, v):
    return {"error": "402 Payment Required"}, 402


@app.errorhandler(403)
@error_wrapper
@auth_desired
@api()
def error_403(e, v):

    return {"error": "403 Forbidden"}, 403


@app.errorhandler(404)
@error_wrapper
@auth_desired
@api()
def error_404(e, v):

    return {"error": "404 Not Found"}, 404


@app.errorhandler(405)
@error_wrapper
@auth_desired
@api()
def error_405(e, v):

    return {"error": "405 Method Not Allowed"}, 405


@app.errorhandler(409)
@error_wrapper
@auth_desired
@api()
def error_409(e, v):

    return {"error": "409 Conflict"}, 409


@app.errorhandler(413)
@error_wrapper
@auth_desired
@api()
def error_413(e, v):

    return {"error": "413 Request Payload Too Large"}, 413


@app.errorhandler(422)
@error_wrapper
@auth_desired
@api()
def error_422(e, v):

    return {"error": "422 Unprocessable Entity"}, 422


@app.errorhandler(429)
@error_wrapper
@auth_desired
@api()
def error_429(e, v):

    ip=request.remote_addr

    #get recent violations
    if r:
        count_429s = r.get(f"429_count_{ip}")
        if not count_429s:
            count_429s=0
        else:
            count_429s=int(count_429s)

        count_429s+=1

        r.set(f"429_count_{ip}", count_429s)
        r.expire(f"429_count_{ip}", 60)

        #if you exceed 30x 429 without a 60s break, you get IP banned for 1 hr:
        if count_429s>=30:
            try:
                print("triggering IP ban", request.remote_addr, session.get("user_id"), session.get("history"))
            except:
                pass
            
            r.set(f"ban_ip_{ip}", int(time.time()))
            r.expire(f"ban_ip_{ip}", 3600)
            return "", 429



    return {"error": "429 Too Many Requests"}, 429


@app.errorhandler(451)
@error_wrapper
@auth_desired
@api()
def error_451(e, v):

    return {"error": "451 Unavailable For Legal Reasons"}


@app.errorhandler(500)
@error_wrapper
@auth_desired
@api()
def error_500(e, v):
    try:
        g.db.rollback()
    except AttributeError:
        pass

    return {"error": "500 Internal Server Error"}


@app.errorhandler(503)
@error_wrapper
@api()
def error_503(e):
    try:
        g.db.rollback()
    except AttributeError:
        pass

    return {"error": "503 Service Unavailable"}, 503


@app.errorhandler(DatabaseOverload)
@error_wrapper
@auth_desired
@api()
def error_db_overload(e, v):
    return {"error": "500 Internal Server Error (database overload)"}, 500
