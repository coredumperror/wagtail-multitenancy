{% load i18n wagtailadmin_tags %}
{% comment %}
    Variables accepted by this template:

    query_parameters - a query string (without the '?') to be placed after the search URL

    tabbed - if true, add the classname 'tab-merged'
    merged - if true, add the classname 'merged'
{% endcomment %}
<header class="nice-padding users {% if merged %}merged{% endif %} {% if tabbed %}tab-merged{% endif %} {% if search_form %}hasform{% endif %}">
  <div class="row">
    <div class="left">
      <div class="col">
          <h1 class="icon icon-user">Users</h1>
      </div>
      <form class="col search-form" action="{% url 'wagtailusers_users:index' %}{% if query_parameters %}?{{ query_parameters }}{% endif %}" method="get">
        <ul class="fields">
          {% for field in search_form %}
            {% include "wagtailadmin/shared/field_as_li.html" with field=field field_classes="field-small iconfield" input_classes="icon-search" %}
          {% endfor %}
          <li class="submit visuallyhidden"><input type="submit" value="Search" class="button" /></li>
        </ul>
      </form>
    </div>
    <div class="right">
      {% usage_count_enabled as uc_enabled %}
      {% if uc_enabled and usage_object %}
        <div class="usagecount">
          <a href="{{ usage_object.usage_url }}">{% blocktrans count useage_count=usage_object.get_usage.count %}Used {{ useage_count  }} time{% plural %}Used {{ useage_count }} times{% endblocktrans %}</a>
        </div>
      {% endif %}
        <div id="add-user" class="addbutton">
          <a href="{% url 'wagtailusers_users:add' %}" class="button bicolor icon icon-plus">Add an LDAP User</a>
        </div>
        <div id="add-local-user" class="addbutton">
          <a href="{% url 'wagtailusers_users:add_local' %}" class="button bicolor icon icon-plus">Add a Local User</a>
        </div>
    </div>
  </div>
</header>
