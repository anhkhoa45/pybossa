import requests
from minio import Minio
import json
client = Minio('127.0.0.1:9000',
               access_key='ManhNguyen98',
               secret_key='12345678',
               secure=False)

class MinioClient(object):

    def objects(self, bucket_name):
        objects = client.list_objects('%s' % bucket_name, recursive=True)
        if objects:
            response = []
            for obj in objects:
                temp = {"object_name": obj.object_name, "size": obj.size}
                response.append(temp)
            return response
        else:
            return 'Bucket "%s" does not exist' % bucket_name