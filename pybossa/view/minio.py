import json
from flask import Blueprint, Response
from pybossa.minio_client import MinioClient

blueprint = Blueprint('minio', __name__)

@blueprint.route('/bucket/<string:accesskey>/<string:secretkey>/<string:bucket>')
def objects(accesskey, secretkey, bucket):
    try:
        bucket_objects = MinioClient().objects(accesskey, secretkey, bucket)
        return json.dumps(bucket_objects), 200
    except :
        error = dict(action='GET',
                     status="failed",
                     status_code=404,
                     exception_msg=str('Bucket "%s" does not exist' % bucket))
        return Response(json.dumps(error), status=404,
                        mimetype='application/json')
