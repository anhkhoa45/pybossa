# -*- coding: utf8 -*-
# This file is part of PYBOSSA.
#
# Copyright (C) 2015 Scifabric LTD.
#
# PYBOSSA is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PYBOSSA is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with PYBOSSA.  If not, see <http://www.gnu.org/licenses/>.
"""
PYBOSSA api module for exposing domain objects via an API.

This package adds GET, POST, PUT and DELETE methods for:
    * projects,
    * categories,
    * tasks,
    * task_runs,
    * users,
    * global_stats,
    * helpingmaterial,
    * page

"""
from pdfminer import utils
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage, PDFTextExtractionNotAllowed
from pdfminer.pdfdevice import PDFDevice, TagExtractor
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import PDFLayoutAnalyzer, PDFConverter, XMLConverter, PDFPageAggregator
from pdfminer.image import ImageWriter
from pdfminer.cmapdb import CMapDB
from pdfminer.pdfdevice import PDFTextDevice
from pdfminer.pdffont import PDFUnicodeNotDefined
from pdfminer.layout import LAParams, LTContainer, LTPage, LTText, LTLine, LTRect, LTCurve, LTFigure, LTImage, LTChar, LTTextLine, LTTextBox, LTTextBoxVertical, LTTextGroup
from pdfminer.utils import apply_matrix_pt, mult_matrix, enc, bbox2str

from flask import Flask, jsonify, request, render_template
from lxml import etree
import wget
import os
from os.path import join
import io
import re
import requests
from anno import Anno

""""""
import json
import jwt
from flask import Blueprint, request, abort, Response, make_response
from flask import current_app
from flask_login import current_user
from werkzeug.exceptions import NotFound
from pybossa.util import jsonpify, get_user_id_or_ip, fuzzyboolean
from pybossa.util import get_disqus_sso_payload
import pybossa.model as model
from pybossa.core import csrf, ratelimits, sentinel, anonymizer
from pybossa.ratelimit import ratelimit
from pybossa.cache.projects import n_tasks
import pybossa.sched as sched
from pybossa.error import ErrorStatus
from global_stats import GlobalStatsAPI
from task import TaskAPI
from task_run import TaskRunAPI
from project import ProjectAPI
from announcement import AnnouncementAPI
from blogpost import BlogpostAPI
from category import CategoryAPI
from favorites import FavoritesAPI
from user import UserAPI
from token import TokenAPI
from result import ResultAPI
from project_stats import ProjectStatsAPI
from helpingmaterial import HelpingMaterialAPI
from page import PageAPI
from pybossa.core import project_repo, task_repo
from pybossa.contributions_guard import ContributionsGuard
from pybossa.auth import jwt_authorize_project
from werkzeug.exceptions import MethodNotAllowed

blueprint = Blueprint('api', __name__)

error = ErrorStatus()

pg = None
root = None
annos = []
tree = None

@blueprint.route('/')
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def index():  # pragma: no cover
    """Return dummy text for welcome page."""
    return 'The %s API' % current_app.config.get('BRAND')


def register_api(view, endpoint, url, pk='id', pk_type='int'):
    """Register API endpoints.

    Registers new end points for the API using classes.

    """
    view_func = view.as_view(endpoint)
    csrf.exempt(view_func)
    blueprint.add_url_rule(url,
                           view_func=view_func,
                           defaults={pk: None},
                           methods=['GET', 'OPTIONS'])
    blueprint.add_url_rule(url,
                           view_func=view_func,
                           methods=['POST', 'OPTIONS'])
    blueprint.add_url_rule('%s/<%s:%s>' % (url, pk_type, pk),
                           view_func=view_func,
                           methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])

register_api(ProjectAPI, 'api_project', '/project', pk='oid', pk_type='int')
register_api(ProjectStatsAPI, 'api_projectstats', '/projectstats', pk='oid', pk_type='int')
register_api(CategoryAPI, 'api_category', '/category', pk='oid', pk_type='int')
register_api(TaskAPI, 'api_task', '/task', pk='oid', pk_type='int')
register_api(TaskRunAPI, 'api_taskrun', '/taskrun', pk='oid', pk_type='int')
register_api(ResultAPI, 'api_result', '/result', pk='oid', pk_type='int')
register_api(UserAPI, 'api_user', '/user', pk='oid', pk_type='int')
register_api(AnnouncementAPI, 'api_announcement', '/announcement', pk='oid', pk_type='int')
register_api(BlogpostAPI, 'api_blogpost', '/blogpost', pk='oid', pk_type='int')
register_api(HelpingMaterialAPI, 'api_helpingmaterial',
             '/helpingmaterial', pk='oid', pk_type='int')
register_api(PageAPI, 'api_page',
             '/page', pk='oid', pk_type='int')
register_api(GlobalStatsAPI, 'api_globalstats', '/globalstats',
             pk='oid', pk_type='int')
register_api(FavoritesAPI, 'api_favorites', '/favorites',
             pk='oid', pk_type='int')
register_api(TokenAPI, 'api_token', '/token', pk='token', pk_type='string')


@jsonpify
@blueprint.route('/project/<project_id>/newtask')
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def new_task(project_id):
    """Return a new task for a project."""
    # Check if the request has an arg:
    try:
        tasks = _retrieve_new_task(project_id)

        if type(tasks) is Response:
            return tasks

        # If there is a task for the user, return it
        if tasks is not None:
            guard = ContributionsGuard(sentinel.master)
            for task in tasks:
                guard.stamp(task, get_user_id_or_ip())
            data = [task.dictize() for task in tasks]
            if len(data) == 0:
                response = make_response(json.dumps({}))
            elif len(data) == 1:
                response = make_response(json.dumps(data[0]))
            else:
                response = make_response(json.dumps(data))
            response.mimetype = "application/json"
            return response
        return Response(json.dumps({}), mimetype="application/json")
    except Exception as e:
        return error.format_exception(e, target='project', action='GET')


def _retrieve_new_task(project_id):

    project = project_repo.get(project_id)

    if project is None:
        raise NotFound

    if not project.allow_anonymous_contributors and current_user.is_anonymous():
        info = dict(
            error="This project does not allow anonymous contributors")
        error = [model.task.Task(info=info)]
        return error

    if request.args.get('external_uid'):
        resp = jwt_authorize_project(project,
                                     request.headers.get('Authorization'))
        if resp != True:
            return resp

    if request.args.get('limit'):
        limit = int(request.args.get('limit'))
    else:
        limit = 1

    if limit > 100:
        limit = 100

    if request.args.get('offset'):
        offset = int(request.args.get('offset'))
    else:
        offset = 0

    if request.args.get('orderby'):
        orderby = request.args.get('orderby')
    else:
        orderby = 'id'

    if request.args.get('desc'):
        desc = fuzzyboolean(request.args.get('desc'))
    else:
        desc = False

    user_id = None if current_user.is_anonymous() else current_user.id
    user_ip = (anonymizer.ip(request.remote_addr or '127.0.0.1')
               if current_user.is_anonymous() else None)
    external_uid = request.args.get('external_uid')
    task = sched.new_task(project_id, project.info.get('sched'),
                          user_id,
                          user_ip,
                          external_uid,
                          offset,
                          limit,
                          orderby=orderby,
                          desc=desc)
    return task


@jsonpify
@blueprint.route('/app/<short_name>/userprogress')
@blueprint.route('/project/<short_name>/userprogress')
@blueprint.route('/app/<int:project_id>/userprogress')
@blueprint.route('/project/<int:project_id>/userprogress')
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def user_progress(project_id=None, short_name=None):
    """API endpoint for user progress.

    Return a JSON object with two fields regarding the tasks for the user:
        { 'done': 10,
          'total: 100
        }
       This will mean that the user has done a 10% of the available tasks for
       him

    """
    if project_id or short_name:
        if short_name:
            project = project_repo.get_by_shortname(short_name)
        elif project_id:
            project = project_repo.get(project_id)

        if project:
            # For now, keep this version, but wait until redis cache is
            # used here for task_runs too
            query_attrs = dict(project_id=project.id)
            if current_user.is_anonymous():
                query_attrs['user_ip'] = anonymizer.ip(request.remote_addr or
                                                       '127.0.0.1')
            else:
                query_attrs['user_id'] = current_user.id
            taskrun_count = task_repo.count_task_runs_with(**query_attrs)
            tmp = dict(done=taskrun_count, total=n_tasks(project.id))
            return Response(json.dumps(tmp), mimetype="application/json")
        else:
            return abort(404)
    else:  # pragma: no cover
        return abort(404)


@jsonpify
@blueprint.route('/auth/project/<short_name>/token')
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def auth_jwt_project(short_name):
    """Create a JWT for a project via its secret KEY."""
    project_secret_key = None
    if 'Authorization' in request.headers:
        project_secret_key = request.headers.get('Authorization')
    if project_secret_key:
        project = project_repo.get_by_shortname(short_name)
        if project and project.secret_key == project_secret_key:
            token = jwt.encode({'short_name': short_name,
                                'project_id': project.id},
                               project.secret_key, algorithm='HS256')
            return token
        else:
            return abort(404)
    else:
        return abort(403)


@jsonpify
@blueprint.route('/disqus/sso')
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def get_disqus_sso_api():
    """Return remote_auth_s3 and api_key for disqus SSO."""
    try:
        if current_user.is_authenticated():
            message, timestamp, sig, pub_key = get_disqus_sso_payload(current_user)
        else:
            message, timestamp, sig, pub_key = get_disqus_sso_payload(None)

        if message and timestamp and sig and pub_key:
            remote_auth_s3 = "%s %s %s" % (message, sig, timestamp)
            tmp = dict(remote_auth_s3=remote_auth_s3, api_key=pub_key)
            return Response(json.dumps(tmp), mimetype='application/json')
        else:
            raise MethodNotAllowed
    except MethodNotAllowed as e:
        e.message = "Disqus keys are missing"
        return error.format_exception(e, target='DISQUS_SSO', action='GET')

@jsonpify
@blueprint.route('/task/<short_name>/submittask', methods=['GET'])
def submit_task(project_id=None, short_name=None):
    datas = request.get_json()
    init(datas[0]['documentId'])
    for data in datas:
        annolist = data['annotations']
        page = data['pageNumber']

        for anno in annolist:
            if anno['type'] == "area":
                anno['page'] = page
                add_anno(anno)
            elif anno['type'] == "highlight" or anno['type'] == "strikeout":
                for rectangle in anno['rectangles']:
                    n_anno = anno
                    n_anno.update(rectangle)
                    anno['page'] = page
                    add_anno(n_anno)
    finish(datas[0]['documentId'])
    return "ok", 200

def init(url):
    global pg, root, tree

    r = requests.get(url, verify=False)
    with open('result-file/tmp.pdf', 'wb') as f:
        f.write(r.content)

    inf = open('result-file/tmp.pdf', 'rb')
    outf = open('result-file/tmp.xml', 'wb')
    pg = convert_xml(inf, outf)
    inf.close()
    outf.close()

    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse("result-file/tmp.xml", parser)
    root = tree.getroot()
    root = clear_xml(root)

def add_anno(r_anno):
    global annos, root, pg
    anno = tranform(pg, r_anno)
    tag_covered = anno.browse(root)
    anno.elements = tag_covered
    annos.append(anno)

def finish(url):
    global pg, root, annos, tree
    PATH_XML = 'result-file/' + url.split('/')[-1].split('.')[0] + '.xml'
    # print (PATH_XML)
    for anno in annos:
        add_annotate_tag(anno)
    merge_annotate_tag(root)
    tree.write(PATH_XML, pretty_print=True)
    os.remove('result-file/tmp.xml')
    os.remove('result-file/tmp.pdf')
    pg, root, annos = (None, None, [])


def convert_xml(inf, outf, page_numbers=None, output_type='xml', codec='utf-8', laparams=None,
                maxpages=0, scale=1.0, rotation=0, output_dir=None, strip_control=False,
                debug=False, disable_caching=False):
    laparams = LAParams()
    imagewriter = None
    if output_dir:
        imagewriter = ImageWriter(output_dir)

    rsrcmgr = PDFResourceManager(caching=not disable_caching)

    device = XMLConverter(rsrcmgr, outf, codec='utf-8', laparams=laparams,
                        imagewriter=imagewriter,
                        )

    interpreter = PDFPageInterpreter(rsrcmgr, device)
    for page in PDFPage.get_pages(inf,
                                page_numbers,
                                maxpages=maxpages,
                                caching=not disable_caching,
                                check_extractable=True):
        page.rotate = (page.rotate + rotation) % 360
        interpreter.process_page(page)
    device.close()
    return page


def tranform(page, r_anno):
    mediabox = page.mediabox
    # print mediabox
    x1 = r_anno['x'] - 2 if 'x' in r_anno  else r_anno['x1'] - 2
    y1 = mediabox[3] - r_anno['y'] - r_anno['height'] - 2 if 'y' in r_anno else mediabox[3] - r_anno['y1'] - 2
    x2 = x1 + r_anno['width'] + 4 if 'x' in r_anno  else r_anno['x2'] - 2
    y2 = y1 + r_anno['height'] + 4 if 'y' in r_anno else mediabox[3] - r_anno['y2'] - 2

    anno = Anno(x1, y1, x2, y2, r_anno['page'],
                r_anno['type'], r_anno['entity'])
    return anno


special_character = " !\"#$%&'()*+,-./:;<=>?@[\]^_`{|}~"
def clear_xml(tag):
    if len(tag) > 0:
        for subtag in tag:
            clear_xml(subtag)
        if len(tag) == 0:
            tag.getparent().remove(tag)
    elif tag.tag == "text" and "bbox" not in tag.attrib:
        tag.getparent().remove(tag)
    elif tag.text is None:
        tag.getparent().remove(tag)
    elif not tag.text.isalpha() and not tag.text.isdigit() and tag.text not in special_character:
        tag.getparent().remove(tag)
    return tag


# Search frame of tag, is bottom-left and top-right
def get_border_of_elements(elements):
    bx1 = 99999
    by1 = 99999
    bx2 = -99999
    by2 = -99999
    for i in elements:
        x1, y1, x2, y2 = [float(x) for x in i.attrib['bbox'].split(',')]
        if x1 < bx1:
            bx1 = x1
        if y1 < by1:
            by1 = y1
        if x2 > bx2:
            bx2 = x2
        if y2 > by2:
            by2 = y2
    bbox = str(bx1) + ',' + str(by1) + ',' + str(bx2) + ',' + str(by2)
    return (bbox)

# Add frame anno
def add_annotate_tag(anno):
    # print anno.elements
    for element in anno.elements:
        parent = element.getparent()
        index = parent.index(element)
        bbox = element.attrib['bbox']

        if parent.tag == "Annotate" and parent.attrib['label'] == anno.label and parent.attrib['bbox'] == bbox:
            continue

        anno_tag = etree.Element("Annotate")
        anno_tag.set("bbox", bbox)
        anno_tag.set("label", anno.label)
        anno_tag.insert(len(anno_tag), element)
        parent.insert(index, anno_tag)


# Merge nearest annotate tag
def merge_annotate_tag(tag):
    index = 0
    while True:
        if index >= len(tag):
            break
        inner_tag = tag[index]
        merge_annotate_tag(inner_tag)
        if inner_tag.tag == "Annotate":
            anno_tag = etree.Element("Annotate")
            label = inner_tag.attrib['label']
            i = index
            while i < len(tag) and tag[i].tag == "Annotate" and tag[i].attrib['label'] == label:
                merge_annotate_tag(tag[i])
                for tg in tag[i]:
                    anno_tag.insert(len(anno_tag), tg)
                tag.remove(tag[i])
            anno_tag.set('bbox', get_border_of_elements(anno_tag))
            anno_tag.set('label', inner_tag.attrib['label'])
            tag.insert(index, anno_tag)
        index += 1
