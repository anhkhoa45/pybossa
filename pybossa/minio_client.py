import requests
from minio import Minio
import json
from datetime import timedelta

class MinioClient(object):

    def objects(self,accesskey , secretkey, bucket_name):
        client = Minio('127.0.0.1:9000',
               access_key='%s' % accesskey,
               secret_key='%s' % secretkey,
               secure=False)
        objects = client.list_objects('%s' % bucket_name, recursive=True)
        if objects:
            response = []
            for obj in objects:
                temp = {"object_name": obj.object_name, "size": obj.size}
                response.append(temp)
            return response
        else:
            return 'Bucket "%s" does not exist' % bucket_name

    def url(self, accesskey, secretkey, bucket, filename):
        client = Minio('127.0.0.1:9000',
               access_key='%s' % accesskey,
               secret_key='%s' % secretkey,
               secure=False)
        url = client.presigned_get_object(bucket, filename, expires=timedelta(days=7))
        return url