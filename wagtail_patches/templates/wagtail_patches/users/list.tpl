{% load gravatar wagtail_patches_tags %}

<table class="listing">
  <thead>
    <tr>
      <th class="name">
        Name
        {% if ordering == "name" %}
          <a href="{% url 'wagtailusers_users:index' %}?ordering=-name" class="icon icon-arrow-down-after teal"></a>
        {% elif ordering == "-name" %}
          <a href="{% url 'wagtailusers_users:index' %}" class="icon icon-arrow-up-after teal"></a>
        {% else %}
          <a href="{% url 'wagtailusers_users:index' %}?ordering=name" class="icon icon-arrow-down-after"></a>
        {% endif %}
      </th>
      <th class="username">
        Username
        {% if ordering == "username" %}
          <a href="{% url 'wagtailusers_users:index' %}?ordering=-username" class="icon icon-arrow-down-after teal"></a>
        {% elif ordering == "-username" %}
          <a href="{% url 'wagtailusers_users:index' %}" class="icon icon-arrow-up-after teal"></a>
        {% else %}
          <a href="{% url 'wagtailusers_users:index' %}?ordering=username" class="icon icon-arrow-down-after"></a>
        {% endif %}
      </th>
      <th class="groups">Groups</th>
      <th class="status">Status</th>
    </tr>
  </thead>
  <tbody>
    {% for user in users %}
      <tr>
        <td class="title">
          <h2>
            <span class="avatar small icon icon-user"><img src="{% gravatar_url user.email 25 %}"></span>
            <a href="{% url 'wagtailusers_users:edit' user.pk %}">{{ user.get_full_name|default:user.de_namespaced_username }}</a>
          </h2>
        </td>
        <td class="username">{{ user.de_namespaced_username }}</td>
        <td class="groups">
          {% render_site_specific_groups user request %}
        </td>
        <td class="status">
          <div class="status-tag {% if user.is_active %}primary{% endif %}">
            {% if user.is_active %}Active{% else %}Inactive{% endif %}
          </div>
        </td>
      </tr>
    {% endfor %}
  </tbody>
</table>
