{% if groups %}
    {% include "wagtail_patches/groups/list.tpl" %}
    {% include "wagtailadmin/shared/pagination_nav.html" with items=groups is_searching=is_searching linkurl="wagtailusers_groups:index" %}
{% else %}
    {% url 'wagtailusers_groups:add' as wagtailusers_create_group_url %}
    <p>There are no groups configured. Why not <a href="{{ wagtailusers_create_group_url }}">add some</a>?</p>
{% endif %}
