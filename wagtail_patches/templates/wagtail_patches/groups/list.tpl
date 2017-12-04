{% load wagtail_patches_tags %}

<table class="listing">
  <thead>
    <tr>
      <th class="name">
        Name
        {% if ordering == "name" %}
          <a href="{% url 'wagtailusers_groups:index' %}?ordering=-name" class="icon icon-arrow-down-after teal"></a>
        {% elif ordering == "-name" %}
          <a href="{% url 'wagtailusers_groups:index' %}" class="icon icon-arrow-up-after teal"></a>
        {% else %}
          <a href="{% url 'wagtailusers_groups:index' %}?ordering=name" class="icon icon-arrow-down-after"></a>
        {% endif %}
      </th>
    </tr>
  </thead>
  <tbody>
    {% for group in groups %}
      <tr>
        <td class="title">
          <h2>
            <a href="{% url 'wagtailusers_groups:edit' group.id %}">{% site_specific_group_name group request %}</a>
          </h2>
        </td>
      </tr>
    {% endfor %}
  </tbody>
</table>
