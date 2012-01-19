#-*- coding:utf-8 -*-
import os
from flask import g, session, request, send_from_directory, \
    redirect, url_for, abort, render_template, flash

import config
from past.corelib import auth_user_from_session, set_user_cookie, logout_user
from past.utils.escape import json_encode, json_decode
from past.model.user import User, UserAlias, OAuth2Token
from past.model.status import SyncTask, Status
from past.oauth_login import DoubanLogin, SinaLogin, OAuthLoginError
import api_client

from past import app

@app.before_request
def before_request():
    g.user = auth_user_from_session(session)
    g.start = int(request.args.get('start', 0))
    g.count = int(request.args.get('count', 20))
    print '--- user is:%s' % g.user

@app.teardown_request
def teardown_request(exception):
    pass

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
        "favicon.ico", mimetype="image/vnd.microsoft.icon")

@app.route("/")
def index():
    if not g.user:
        return redirect(url_for("connect"))

    cate = request.args.get("cate", None)
    ids = Status.get_ids(user_id=g.user.id, start=g.start, limit=g.count, cate=cate)
    status_list = Status.gets(ids)
    return render_template("timeline.html", status_list=status_list, config=config)

@app.route("/user/<uid>")
def user(uid):
    u = User.get(uid)
    return u.name

@app.route("/logout")
def logout():
    if not g.user:
        return "you are not login"
    r = logout_user(g.user)
    return "logout succ"

@app.route("/connect/", defaults={"provider": config.OPENID_DOUBAN})
@app.route("/connect/<provider>")
def connect(provider):
    d = config.APIKEY_DICT.get(provider)
    login_service = None
    if provider == config.OPENID_DOUBAN:
        login_service = DoubanLogin(d['key'], d['secret'], d['redirect_uri'])
    elif provider == config.OPENID_SINA:
        login_service = SinaLogin(d['key'], d['secret'], d['redirect_uri'])
    print '---- login_service:', d,login_service
    if not login_service:
        abort(404)

    login_uri = login_service.get_login_uri()
    return redirect(login_uri)

## 这里其实是所有的登陆入口
@app.route("/connect/<provider>/callback")
def connect_callback(provider):
    code = request.args.get("code")
    if not code:
        abort(401)

    d = config.APIKEY_DICT.get(provider)
    login_service = None
    if provider == config.OPENID_DOUBAN:
        openid_type = config.OPENID_TYPE_DICT[config.OPENID_DOUBAN]
        login_service = DoubanLogin(d['key'], d['secret'], d['redirect_uri'])
    elif provider == config.OPENID_SINA:
        openid_type = config.OPENID_TYPE_DICT[config.OPENID_SINA]
        login_service = SinaLogin(d['key'], d['secret'], d['redirect_uri'])

    if not login_service:
        abort(404)

    try:
        token_dict = login_service.get_access_token(code)
    except OAuthLoginError, e:
        abort(401, e.msg)
    if not ( token_dict and token_dict.get("access_token") ):
        abort(401, "no_access_token")
    
    try:
        user_info = login_service.get_user_info(
            token_dict.get("access_token"), token_dict.get("uid"))
    except OAuthLoginError, e:
        abort(401, e.msg)

    if not user_info:
        abort(401, "no_user_info")
    
    ua = UserAlias.get(openid_type, user_info.get_user_id())
    if not ua:
        if not g.user:
            ua = UserAlias.create_new_user(openid_type,
                    user_info.get_user_id(), user_info.get_nickname())
        else:
            ua = UserAlias.bind_to_exists_user(g.user, 
                    openid_type, user_info.get_user_id())
    if not ua:
        abort(401)

    ##设置个人资料（头像等等）
    u = User.get(ua.user_id)
    u.set_avatar_url(user_info.get_avatar())
    u.set_icon_url(user_info.get_icon())

    OAuth2Token.add(ua.id, token_dict.get("access_token"), 
            token_dict.get("refresh_token", ""))

    if not g.user:
        g.user = User.get(ua.user_id)
        set_user_cookie(g.user, session)
    
    return redirect(url_for('index'))


@app.route("/sync/<provider>/<cates>")
def sync(provider,cates):
    if provider not in (config.OPENID_DOUBAN, 
            config.OPENID_SINA, config.OPENID_WORDPRESS):
        abort(401, "暂时不支持其他服务")
    cates = cates.split("|")

    return _sync(provider, cates)

def _sync(provider, cates):

    if not (cates and isinstance(cates, list)):
        return "no cates"

    cates = filter(lambda x: x in [str(y) for y in config.CATE_LIST], cates)
    if not cates:
        abort(400, "not support such cates")

    redir = "/connect/%s" % provider

    if not g.user:
        print '--- no g.user...'
        return redirect(redir)

    uas = UserAlias.gets_by_user_id(g.user.id)
    print '--- uas:', uas
    r = filter(lambda x: x.type == config.OPENID_TYPE_DICT[provider], uas)
    user_alias = r and r[0]
    
    if not user_alias:
        print '--- no user_alias...'
        return redirect(redir)

    token = OAuth2Token.get(user_alias.id)   
    
    if not token:
        print '--- no token...'
        return redirect(redir)

    for c in cates:
        SyncTask.add(c, g.user.id)
    
    flash("good, %s sync task add succ..." % provider)

    return "%s sync task add succ..." % provider
