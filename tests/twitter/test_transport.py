import json
import pytest
from twitter_skill._errors import TwitterError
from twitter_skill._transport import classify

@pytest.mark.parametrize('status,body,error,code', [
    (403,'<!DOCTYPE html>cf-challenge','challenge',5),
    (429,{'errors':[{'code':326}]},'account_locked',5),
    (200,{'errors':[{'code':64}]},'account_locked',5),
    (200,{'data':{'user':{'result':{'__typename':'UserUnavailable'}}}},'unavailable',9),
    (429,{},'rate_limit',5),(401,{},'session',4),
    (200,{'errors':[{'code':32}]},'session',4),
    (403,{'errors':[{'code':353}]},'csrf',4),
    (404,'','transaction_rejected',6),
    (400,{'errors':[{'message':'The following features cannot be null: new_flag'}]},'operation_rotated',6),
    (422,{'errors':[{'message':'Variable x must be defined'}]},'contract_drift',6),
    (502,'bad','transient',6),(200,{'data':{}},'unavailable',9),
    (200,{'data':{'different':[]}},'envelope_drift',6)])
def test_classify(status,body,error,code):
    with pytest.raises(TwitterError) as exc:
        classify({'status':status,'body':json.dumps(body) if isinstance(body,dict) else body}, 'UserByScreenName', 'data.user.result')
    assert (exc.value.error,exc.value.code)==(error,code)

def test_data_and_warning():
    data,warnings=classify({'status':200,'body':json.dumps({'data':{'list':{'name':'Example'}},'errors':[{'code':214}]})}, 'ListByRestId','data.list')
    assert data['name']=='Example' and len(warnings)==1

@pytest.mark.parametrize('operation,root,body', [
    ('UserByScreenName', 'data.user.result', {'data': {'user': {'result': {'unexpected': 'shape'}}}}),
    ('UserTweets', 'data.user.result.timeline.timeline.instructions', {'data': {'user': {'result': {'timeline': {'timeline': {'instructions': {}}}}}}}),
])
def test_present_but_malformed_root_is_drift(operation, root, body):
    with pytest.raises(TwitterError) as exc:
        classify({'status': 200, 'body': json.dumps(body)}, operation, root)
    assert exc.value.error == 'envelope_drift'
