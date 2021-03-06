{% load wagtailadmin_tags i18n %}

{% if users %}
  {% if is_searching %}
    <h2>
      {% blocktrans count counter=users|length %}
        There is one match
      {% plural %}
        There are {{ counter }} matches
      {% endblocktrans %}
    </h2>
    {% search_other %}
  {% endif %}

  {% include "wagtail_patches/users/list.tpl" %}

  {% include "wagtailadmin/shared/pagination_nav.html" with items=users is_searching=is_searching linkurl="wagtailusers_users:index" %}
{% else %}
  {% if is_searching %}
     <h2>Sorry, no users match "<em>{{ query_string }}</em>"</h2>
     {% search_other %}
  {% else %}
    {% url 'wagtailusers_create' as wagtailusers_create_url %}
    <p>There are no users configured. Why not <a href="{{ wagtailusers_create_url }}">add some</a>?</p>
  {% endif %}
{% endif %}
