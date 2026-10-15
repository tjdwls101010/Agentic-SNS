"""Decoded GraphQL chunks → the skill's records. Pure: no request, `captured_at` comes from the caller."""
from facebook.graphql.records import posts

SCHEMAS = {
    'post': {'object': 'post', 'description': 'A post from feed, profile, group, search or post.', 'fields': posts.FIELDS},
}
