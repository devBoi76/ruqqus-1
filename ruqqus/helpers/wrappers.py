from flask import *
from os import environ
import requests
from werkzeug.wrappers.response import Response as RespObj
import time
import random
import traceback

from ruqqus.classes import *
from .get import *
from .alerts import send_notification
from ruqqus.__main__ import Base, app, db_session


def get_logged_in_user(db=None):

    if not db:
        db=g.db

    if "Authorization" in request.headers:

        token = request.headers.get("Authorization").split()[1]

        try:
            data = jwt.decode(token, app.config.get("SECRET_KEY"), algorithms = ["HS256"])
            uid = data.get("id")
            login_nonce = data.get("login_nonce")

            v = db.query(User).filter_by(
                id=uid,
                is_deleted=False
            ).first()

            if v and (nonce < v.login_nonce):
                x= (None, None)
            else:
                x=(v, None)
        except:
            x = (None, None)

    else:
        x=(None, None)

    if x[0]:
        x[0].client=x[1]

    return x

def check_ban_evade(v):

    if not v or not v.ban_evade:
        return
    
    if random.randint(0,30) < v.ban_evade and not v.is_suspended:
        v.ban(reason="Evading a site-wide ban")
        send_notification(v, "Your Ruqqus account has been permanently suspended for the following reason:\n\n> ban evasion")

        for post in g.db.query(Submission).filter_by(author_id=v.id).all():
            if post.is_banned:
                continue

            post.is_banned=True
            post.ban_reason="Ban evasion. This submission's owner was banned from Ruqqus on another account."
            g.db.add(post)

            ma=ModAction(
                kind="ban_post",
                user_id=1,
                target_submission_id=post.id,
                board_id=post.board_id,
                note="ban evasion"
                )
            g.db.add(ma)

        g.db.commit()

        for comment in g.db.query(Comment).filter_by(author_id=v.id).all():
            if comment.is_banned:
                continue

            comment.is_banned=True
            comment.ban_reason="Ban evasion. This comment's owner was banned from Ruqqus on another account."
            g.db.add(comment)

            ma=ModAction(
                kind="ban_comment",
                user_id=1,
                target_comment_id=comment.id,
                board_id=comment.post.board_id,
                note="ban evasion"
                )
            g.db.add(ma)

        g.db.commit()
        abort(403)

    else:
        v.ban_evade +=1
        g.db.add(v)
        g.db.commit()




# Wrappers
def auth_desired(f):
    # decorator for any view that changes if user is logged in (most pages)

    def wrapper(*args, **kwargs):

        v, c = get_logged_in_user()

        if c:
            kwargs["c"] = c
            
        check_ban_evade(v)
        
        g.v=v

        resp = make_response(f(*args, v=v, **kwargs))
        if v:
            resp.headers.add("Cache-Control", "private")
            resp.headers.add(
                "Access-Control-Allow-Origin",
                app.config["SERVER_NAME"])
        else:
            resp.headers.add("Cache-Control", "public")
        return resp

    wrapper.__name__ = f.__name__
    wrapper.__doc__ = f.__doc__
    return wrapper


def auth_required(f):
    # decorator for any view that requires login (ex. settings)

    def wrapper(*args, **kwargs):

        v, c = get_logged_in_user()

        #print(v, c)

        if not v:
            abort(401)
            
        check_ban_evade(v)

        if c:
            kwargs["c"] = c

        g.v = v

        # an ugly hack to make api work
        resp = make_response(f(*args, v=v, **kwargs))

        resp.headers.add("Cache-Control", "private")
        resp.headers.add(
            "Access-Control-Allow-Origin",
            app.config["SERVER_NAME"])
        return resp

    wrapper.__name__ = f.__name__
    wrapper.__doc__ = f.__doc__
    return wrapper


def is_not_banned(f):
    # decorator that enforces lack of ban

    def wrapper(*args, **kwargs):

        v, c = get_logged_in_user()

        #print(v, c)

        if not v:
            abort(401)
            
        check_ban_evade(v)

        if v.is_suspended:
            abort(403)

        if c:
            kwargs["c"] = c

        g.v = v

        resp = make_response(f(*args, v=v, **kwargs))
        resp.headers.add("Cache-Control", "private")
        resp.headers.add(
            "Access-Control-Allow-Origin",
            app.config["SERVER_NAME"])
        return resp

    wrapper.__name__ = f.__name__
    wrapper.__doc__ = f.__doc__
    return wrapper

# Require tos agreement


def tos_agreed(f):

    def wrapper(*args, **kwargs):

        v = kwargs['v']

        cutoff = int(environ.get("tos_cutoff", 0))

        if v.tos_agreed_utc > cutoff:
            return f(*args, **kwargs)
        else:
            return redirect("/help/terms#agreebox")

    wrapper.__name__ = f.__name__
    wrapper.__doc__ = f.__doc__
    return wrapper

def premium_required(f):

    #decorator that enforces valid premium status
    #use under auth_required or is_not_banned

    def wrapper(*args, **kwargs):

        v=kwargs["v"]

        if not v.has_premium:
            abort(403)

        return f(*args, **kwargs)

    wrapper.__name__=f.__name__
    wrapper.__doc__ = f.__doc__
    return wrapper


def no_negative_balance(s):

    def wrapper_maker(f):

    #decorator that enforces valid premium status
    #use under auth_required or is_not_banned

        def wrapper(*args, **kwargs):

            v=kwargs["v"]

            if v.negative_balance_cents:
                if s=="toast":
                    return jsonify({"error":"You can't do that while your account balance is negative. Visit your account settings to bring your balance up to zero."}), 402
                elif s=="html":
                    raise(PaymentRequired)
                else:
                    raise(PaymentRequired)

            return f(*args, **kwargs)

        wrapper.__name__=f.__name__
        wrapper.__doc__ = f.__doc__
        return wrapper

    return wrapper_maker

def is_guildmaster(*perms):
    # decorator that enforces guildmaster status and verifies permissions
    # use under auth_required
    def wrapper_maker(f):

        def wrapper(*args, **kwargs):

            v = kwargs["v"]
            boardname = kwargs.get("guildname", kwargs.get("boardname"))
            board_id = kwargs.get("bid")
            bid=request.values.get("bid", request.values.get("board_id"))

            if boardname:
                board = get_guild(boardname)
            elif board_id:
                board = get_board(board_id)
            elif bid:
                board = get_board(bid)
            else:
                return jsonify({"error": f"no guild specified"}), 400

            m=board.has_mod(v)
            if not m:
                return jsonify({"error":f"You aren't a guildmaster of +{board.name}"}), 403

            if perms:
                for perm in perms:
                    if not m.__dict__.get(f"perm_{perm}") and not m.perm_full:
                        return jsonify({"error":f"Permission `{perm}` required"}), 403


            if v.is_banned and not v.unban_utc:
                abort(403)

            return f(*args, board=board, **kwargs)

        wrapper.__name__ = f.__name__
        wrapper.__doc__ = f"<small>guildmaster permissions: <code>{', '.join(perms)}</code></small><br>{f.__doc__}" if perms else f.__doc__
        return wrapper

    return wrapper_maker


# this wrapper takes args and is a bit more complicated
def admin_level_required(x):

    def wrapper_maker(f):

        def wrapper(*args, **kwargs):

            v, c = get_logged_in_user()

            if c:
                return jsonify({"error": "No admin api access"}), 403

            if not v:
                abort(401)

            if v.is_banned:
                abort(403)

            if v.admin_level < x:
                abort(403)

            g.v = v

            response = f(*args, v=v, **kwargs)

            if isinstance(response, tuple):
                resp = make_response(response[0])
            else:
                resp = make_response(response)

            resp.headers.add("Cache-Control", "private")
            resp.headers.add(
                "Access-Control-Allow-Origin",
                app.config["SERVER_NAME"])
            return resp

        wrapper.__name__ = f.__name__
        wrapper.__doc__ = f.__doc__
        return wrapper

    return wrapper_maker


def validate_formkey(f):
    """Always use @auth_required or @admin_level_required above @validate_form"""

    def wrapper(*args, v, **kwargs):

        if not request.path.startswith("/api/v1"):

            submitted_key = request.values.get("formkey", "none")

            if not submitted_key:

                abort(401)

            elif not v.validate_formkey(submitted_key):
                abort(401)

        return f(*args, v=v, **kwargs)

    wrapper.__name__ = f.__name__
    wrapper.__doc__ = f.__doc__
    return wrapper


def no_cors(f):
    """
    Decorator prevents content being iframe'd
    """

    def wrapper(*args, **kwargs):

        origin = request.headers.get("Origin", None)

        if origin and origin != "https://" + app.config["SERVER_NAME"] and app.config["FORCE_HTTPS"]==1:

            return "This page may not be embedded in other webpages.", 403

        resp = make_response(f(*args, **kwargs))
        resp.headers.add("Access-Control-Allow-Origin",
                         app.config["SERVER_NAME"]
                         )

        return resp

    wrapper.__name__ = f.__name__
    wrapper.__doc__ = f.__doc__
    return wrapper

# wrapper for api-related things that discriminates between an api url
# and an html url for the same content
# f should return {'api':lambda:some_func(), 'html':lambda:other_func()}


def api(*scopes, no_ban=False):

    def wrapper_maker(f):

        def wrapper(*args, **kwargs):

            if request.path.startswith(('/api/v1','/api/v2')):

                v = kwargs.get('v')
                client = kwargs.get('c')

                if client:

                    if not v or not client:
                        return jsonify(
                            {"error": "401 Not Authorized. Invalid or Expired Token"}), 401

                    kwargs.pop('c')

                    # validate app associated with token
                    if client.application.is_banned:
                        return jsonify({"error": f"403 Forbidden. The application `{client.application.app_name}` is suspended."}), 403

                    # validate correct scopes for request
                    for scope in scopes:
                        if not client.__dict__.get(f"scope_{scope}"):
                            return jsonify({"error": f"401 Not Authorized. Scope `{scope}` is required."}), 403

                    if (request.method == "POST" or no_ban) and v.is_suspended:
                        return jsonify({"error": f"403 Forbidden. The user account is suspended."}), 403

                if not v:
                    return jsonify({"error": f"401 Not Authorized. You must log in. from api wrapper"}), 401

                if v.is_suspended:
                    return jsonify({"error": f"403 Forbidden. You are banned."}), 403

                if request.method != "GET" and not client:
                    return jsonify({"error": f"401 Not Authorized. You must use an OAuth access token to create or edit content."}), 401
                    

                result = f(*args, **kwargs)

                if isinstance(result, dict):
                    resp = result['api']()
                else:
                    resp = result

                if not isinstance(resp, RespObj):
                    resp = make_response(resp)

                resp.headers.add("Cache-Control", "private")
                resp.headers.add(
                    "Access-Control-Allow-Origin",
                    app.config["SERVER_NAME"])
                return resp

            else:

                result = f(*args, **kwargs)

                if not isinstance(result, dict):
                    return result

                try:
                    if request.path.startswith('/inpage/'):
                        return result['inpage']()
                    elif request.path.startswith(('/api/vue/','/test/')):
                        return result['api']()
                    else:
                        return result['html']()
                except KeyError:
                    return result

        wrapper.__name__ = f.__name__
        wrapper.__doc__ = f"<small>oauth scopes: <code>{', '.join(scopes)}</code></small><br>{f.__doc__}" if scopes else f.__doc__
        return wrapper

    return wrapper_maker


SANCTIONS=[
    "CU",   #Cuba
    "IR",   #Iran
    "KP",   #North Korea
    "SY",   #Syria
    "TR",   #Turkey
    "VE",   #Venezuela
]

def no_sanctions(f):

    def wrapper(*args, **kwargs):

        if request.headers.get("cf-ipcountry","") in SANCTIONS:
            abort(451)

        return f(*args, **kwargs)

    wrapper.__name__=f.__name__
    wrapper.__doc__ = f.__doc__
    return wrapper



