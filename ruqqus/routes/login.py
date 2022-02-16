from flask import *
import time
import hmac
from os import environ
import re
import random
from urllib.parse import urlencode

from ruqqus.classes import *
from ruqqus.helpers.wrappers import *
from ruqqus.helpers.base36 import *
from ruqqus.helpers.security import *
from ruqqus.helpers.alerts import *
from ruqqus.helpers.get import *
from ruqqus.mail import send_verification_email
from secrets import token_hex


from ruqqus.mail import *
from ruqqus.__main__ import app, limiter

valid_username_regex = re.compile("^[a-zA-Z0-9_]{3,25}$")
valid_password_regex = re.compile("^.{8,100}$")
# valid_email_regex=re.compile("(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)")

def check_for_alts(current_id):
    # account history
    past_accs = set(session.get("history", []))
    past_accs.add(current_id)
    session["history"] = list(past_accs)

    # record alts
    for past_id in session["history"]:

        if past_id == current_id:
            continue

        check1 = g.db.query(Alt).filter_by(
            user1=current_id, user2=past_id).first()
        check2 = g.db.query(Alt).filter_by(
            user1=past_id, user2=current_id).first()

        if not check1 and not check2:

            try:
                new_alt = Alt(user1=past_id,
                              user2=current_id)
                g.db.add(new_alt)

            except BaseException:
                pass

# login post procedure


#@no_cors
@app.route("/api/v2/login", methods=["POST"])
@limiter.limit("6/minute")
def login_post():

    username = request.form.get("username")

    if "@" in username:
        account = g.db.query(User).filter(
            User.email.ilike(username),
            User.is_deleted == False).first()
    else:
        account = get_user(username, graceful=True)

    if not account or account.is_deleted:
        time.sleep(random.uniform(0, 2))
        return {"error": "Invalid username, email or password"}, 403

    if request.form.get("password"):

        if not account.verifyPass(request.form.get("password")):
            time.sleep(random.uniform(0, 2))
            return {"error": "Invalid username, email or password"}, 403

        if account.mfa_secret:
            now = int(time.time())
            hash = generate_hash(f"{account.id}+{now}+2fachallenge")
            return render_template("login_2fa.html",
                                   v=account,
                                   time=now,
                                   hash=hash,
                                   i=random_image(),
                                   redirect=request.form.get("redirect", "/")
                                   )
    elif request.form.get("2fa_token", "x"):
        now = int(time.time())

        if now - int(request.form.get("time")) > 600:
            return redirect('/login')

        formhash = request.form.get("hash")
        if not validate_hash(f"{account.id}+{request.form.get('time')}+2fachallenge",
                             formhash
                             ):
            return redirect("/login")
        
        is_2fa=account.validate_2fa(request.form.get("2fa_token", "").strip())
        is_recovery=safe_compare(request.form.get("2fa_token","").lower().replace(' ',''), account.mfa_removal_code)
        
        if not is_2fa and not is_recovery:
            
            hash = generate_hash(f"{account.id}+{time}+2fachallenge")
            return render_template("login_2fa.html",
                                   v=account,
                                   time=now,
                                   hash=hash,
                                   failed=True,
                                   i=random_image()
                                   )
        elif is_recovery:
            account.mfa_secret=None
            g.db.add(account)
            g.db.commit()

    else:
        abort(400)

    #check_for_alts(account.id)

    account.refresh_selfset_badges()

    return {
        "v": account.json_login,
        "token": account.token
    }

@app.route("/me", methods=["GET"])
@auth_required
def me(v):
    return redirect(v.url)


@app.route("/logout", methods=["POST"])
@auth_required
@validate_formkey
def logout(v):
        
    session["user_id"]=None
    session["session_id"]=None

    session.modified=True

    return redirect("/")


@app.route("/api/v2/signup", methods=["POST"])
#@no_cors
#@auth_desired
def sign_up_post():
    print("post signup")

    #if v:
    #    print("v - abort")
    #    abort(403)

    agent = request.headers.get("User-Agent", None)
    if not agent:
        print("no user agent - abort")
        abort(403)

    # check tor
    # if request.headers.get("CF-IPCountry")=="T1":
    #    return render_template("sign_up_tor.html",
    #        i=random_image()
    #    )

    #form_timestamp = request.form.get("now", '0')
    #form_formkey = request.form.get("formkey", "none")

    #submitted_token = session.get("signup_token", "")
    #if not submitted_token:
    #    abort(400)

    #correct_formkey_hashstr = form_timestamp + submitted_token + agent

    #correct_formkey = hmac.new(key=bytes(environ.get("MASTER_KEY"), "utf-16"),
                              # msg=bytes(correct_formkey_hashstr, "utf-16")
                              # ).hexdigest()

    #now = int(time.time())

    username = request.form.get("username")

    # define function that takes an error message and generates a new signup
    # form
    def new_signup(error):

        args = {"error": error}
        if request.form.get("referred_by"):
            user = g.db.query(User).filter_by(
                id=request.form.get("referred_by")).first()
            if user:
                args["ref"] = user.username

        return redirect(f"/signup?{urlencode(args)}")

    if app.config["DISABLE_SIGNUPS"]:
        return new_signup("New account registration is currently closed. Please come back later.")

    #if now - int(form_timestamp) < 5:
        #print(f"signup fail - {username } - too fast")
    #    return new_signup("There was a problem. Please try again.")

    #if not hmac.compare_digest(correct_formkey, form_formkey):
        #print(f"signup fail - {username } - mismatched formkeys")
    #    return new_signup("There was a problem. Please try again.")

    # check for matched passwords
    #if not request.form.get(
    #        "password") == request.form.get("password_confirm"):
    #    return new_signup("Passwords did not match. Please try again.")

    # check username/pass conditions
    if not re.fullmatch(valid_username_regex, username):
        #print(f"signup fail - {username } - mismatched passwords")
        return {"error", "Invalid username"}, 400

    if not re.fullmatch(valid_password_regex, request.form.get("password")):
        #print(f"signup fail - {username } - invalid password")
        return {"error": "Password must be between 8 and 100 characters."}, 400

    # if not re.match(valid_email_regex, request.form.get("email")):
    #    return new_signup("That's not a valid email.")

    # Check for existing acocunts
    email = request.form.get("email")
    email = email.lstrip().rstrip()
    if not email:
        email = None

    #counteract gmail username+2 and extra period tricks - convert submitted email to actual inbox
    if email and email.endswith("@gmail.com"):
        gmail_username=email.split('@')[0]
        gmail_username=gmail_username.split('+')[0]
        gmail_username=gmail_username.replace('.','')
        email=f"{gmail_username}@gmail.com"


    existing_account = get_user(request.form.get("username"), graceful=True)
    if existing_account and existing_account.reserved:
        return {"error": "That username is reserved"}, 403

    if existing_account or (email and g.db.query(
            User).filter(User.email.ilike(email)).first()):
        # #print(f"signup fail - {username } - email already exists")
        return {"error":  "An account with that username or email already exists."}, 400


    # ip ratelimit
    #previous = g.db.query(User).filter_by(
    #    creation_ip=request.remote_addr).filter(
    #    User.created_utc > int(
    #        time.time()) - 60 * 60).first()
    #if previous:
    #    abort(429)

    # check bot
    if app.config.get("HCAPTCHA_SITEKEY"):
        token = request.form.get("h-captcha-response")
        if not token:
            return new_signup("Unable to verify captcha [1].")

        data = {"secret": app.config["HCAPTCHA_SECRET"],
                "response": token,
                "sitekey": app.config["HCAPTCHA_SITEKEY"]}
        url = "https://hcaptcha.com/siteverify"

        x = requests.post(url, data=data)

        if not x.json()["success"]:
            #print(x.json())
            return new_signup("Unable to verify captcha [2].")

    # kill tokens
    #session.pop("signup_token")

    # get referral
    ref_id = int(request.form.get("referred_by", 0))

    # upgrade user badge
    if ref_id:
        ref_user = g.db.query(User).options(
            lazyload('*')).filter_by(id=ref_id).first()
        if ref_user:
            ref_user.refresh_selfset_badges()
            g.db.add(ref_user)

    # make new user
    try:
        new_user = User(
            username=username,
            original_username = username,
            password=request.form.get("password"),
            email=email,
            created_utc=int(time.time()),
            creation_ip=request.remote_addr,
            referred_by=ref_id or None,
            tos_agreed_utc=int(time.time()),
            creation_region=request.headers.get("cf-ipcountry"),
            ban_evade =  int(any([x.is_suspended for x in g.db.query(User).filter(User.id.in_(tuple(session.get("history", [])))).all() if x]))
            )

        g.db.add(new_user)
        g.db.commit()

    except Exception as e:
        #print(e)
        return {"error": "Please enter a valid email"}, 400

    

    # check alts

    #check_for_alts(new_user.id)

    # send welcome/verify email
    if email:
        send_verification_email(new_user)

    # send welcome message
    text = f"""![](https://media.giphy.com/media/ehmupaq36wyALTJce6/200w.gif)
\n\nWelcome to Ruqqus, {new_user.username}. We're glad to have you here.
\n\nWhile you get settled in, here are a couple of things we recommend for newcomers:
- View the [quickstart guide](https://ruqqus.com/post/86i)
- Personalize your front page by [joining some guilds](/browse)
\n\nYou're welcome to say almost anything protected by the First Amendment here - even if you don't live in the United States.
And since we're committed to [open-source](https://github.com/ruqqus/ruqqus) transparency, your front page (and your posted content) won't be artificially manipulated.
\n\nReally, it's what social media should have been doing all along.
\n\nNow, go enjoy your digital freedom.
\n\n-The Ruqqus Team"""
    send_notification(new_user, text)

    return {
        "v": new_user.json_login,
        "token": new_user.token
    }


@app.route("/forgot", methods=["GET"])
def get_forgot():

    return render_template("forgot_password.html",
                           i=random_image()
                           )


@app.route("/forgot", methods=["POST"])
def post_forgot():

    username = request.form.get("username").lstrip('@')
    email = request.form.get("email",'').lstrip().rstrip()

    email=email.replace("_","\_")

    user = g.db.query(User).filter(
        User.username.ilike(username),
        User.email.ilike(email),
        User.is_deleted == False).first()

    if user:
        # generate url
        now = int(time.time())
        token = generate_hash(f"{user.id}+{now}+forgot+{user.login_nonce}")
        url = f"https://{app.config['SERVER_NAME']}/reset?id={user.id}&time={now}&token={token}"

        send_mail(to_address=user.email,
                  subject="Ruqqus - Password Reset Request",
                  html=render_template("email/password_reset.html",
                                       action_url=url,
                                       v=user)
                  )

    return render_template("forgot_password.html",
                           msg="If the username and email matches an account, you will be sent a password reset email. You have ten minutes to complete the password reset process.",
                           i=random_image())


@app.route("/reset", methods=["GET"])
def get_reset():

    user_id = request.args.get("id")
    timestamp = int(request.args.get("time",0))
    token = request.args.get("token")

    now = int(time.time())

    if now - timestamp > 600:
        return render_template("message.html", 
            title="Password reset link expired",
            error="That password reset link has expired.")

    user = g.db.query(User).filter_by(id=user_id).first()

    if not validate_hash(f"{user_id}+{timestamp}+forgot+{user.login_nonce}", token):
        abort(400)

    if not user:
        abort(404)

    reset_token = generate_hash(f"{user.id}+{timestamp}+reset+{user.login_nonce}")

    return render_template("reset_password.html",
                           v=user,
                           token=reset_token,
                           time=timestamp,
                           i=random_image()
                           )


@app.route("/reset", methods=["POST"])
@auth_desired
def post_reset(v):
    if v:
        return redirect('/')

    user_id = request.form.get("user_id")
    timestamp = int(request.form.get("time"))
    token = request.form.get("token")

    password = request.form.get("password")
    confirm_password = request.form.get("confirm_password")

    now = int(time.time())

    if now - timestamp > 600:
        return render_template("message.html",
                               title="Password reset expired",
                               error="That password reset form has expired.")

    user = g.db.query(User).filter_by(id=user_id).first()

    if not validate_hash(f"{user_id}+{timestamp}+reset+{user.login_nonce}", token):
        abort(400)
    if not user:
        abort(404)

    if not password == confirm_password:
        return render_template("reset_password.html",
                               v=user,
                               token=token,
                               time=timestamp,
                               i=random_image(),
                               error="Passwords didn't match.")

    user.passhash = hash_password(password)
    g.db.add(user)

    return render_template("message_success.html",
                           title="Password reset successful!",
                           message="Login normally to access your account.")
