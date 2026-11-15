"""Facebook reaction ids and the counts sent in feedback.top_reactions."""
KINDS = {
    '1635855486666999': 'like',
    '1678524932434102': 'love',
    '613557422527858': 'care',
    '115940658764963': 'haha',
    '478547315650144': 'wow',
    '908563459236466': 'sad',
    '444813342392137': 'angry',
}


def read(feedback):
    top = feedback.get('top_reactions') if isinstance(feedback, dict) else None
    if not isinstance(top, dict):
        return None
    result = {}
    for edge in top.get('edges') or []:
        if not isinstance(edge, dict) or not isinstance(edge.get('node'), dict):
            continue
        node, count = edge['node'], edge.get('reaction_count')
        identity = node.get('id')
        if not isinstance(identity, (str, int)) or isinstance(identity, bool) or type(count) is not int or count < 0:
            continue
        identity = str(identity)
        name = KINDS.get(identity) or node.get('localized_name') or 'id:' + identity
        result[name] = count
    return result
