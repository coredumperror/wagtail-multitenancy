/* Copied from 517f1871e71e0ceb295dc739b4c835bdae8efc4a (Allow specifying of hallo.js plugins via OPTIONS
in WAGTAILADMIN_RICH_TE...) */

'use strict';

function makeHalloRichTextEditable(id, plugins) {
    var input = $('#' + id);
    var richText = $('<div class="richtext"></div>').html(input.val());
    richText.insertBefore(input);
    input.hide();

    var removeStylingPending = false;
    function removeStyling() {
        /* @jchau: Unilaterally strip style attributes from all pasted elements.) */
        $('*[style]', richText).removeAttr('style');
        // 2017-10-12 rrollins: Also remove classes, but only if they're not from images being embedded by the WYSIWYG.
        $('*[class]', richText).each(function() {
            if ($(this).data('embedtype') != 'image') {
                $(this).removeAttr('class');
            }
        });
        removeStylingPending = false;
    }

    /* Workaround for faulty change-detection in hallo */
    function setModified() {
        var hallo = richText.data('IKS-hallo');
        if (hallo) {
            hallo.setModified();
        }
    }

    var closestObj = input.closest('.object');
    var isRoot = input.closest('.struct-block').length == 0;

    richText.hallo({
        toolbar: 'halloToolbarFixed',
        toolbarCssClass: (closestObj.hasClass('full')) ? 'full' : (closestObj.hasClass('stream-field') && isRoot) ? 'stream-field' : '',
        /* use the passed-in plugins arg if specified, otherwise use the global halloPlugins var */
        plugins: plugins || halloPlugins
    }).bind('hallomodified', function(event, data) {
        input.val(data.content);
        if (!removeStylingPending) {
            setTimeout(removeStyling, 100);
            removeStylingPending = true;
        }
    }).bind('paste drop', function(event, data) {
        setTimeout(function() {
            removeStyling();
            setModified();
        }, 1);
    /* Animate the fields open when you click into them. */
    }).bind('halloactivated', function(event, data) {
        $(event.target).addClass('expanded', 200, function(e) {
            /* Hallo's toolbar will reposition itself on the scroll event.
            This is useful since animating the fields can cause it to be
            positioned badly initially. */
            $(window).trigger('scroll');
        });
    }).bind('hallodeactivated', function(event, data) {
        $(event.target).removeClass('expanded', 200, function(e) {
            $(window).trigger('scroll');
        });
    });

    setupLinkTooltips(richText);
}

function setupLinkTooltips(elem) {
    elem.tooltip({
        animation: false,
        title: function() {
            return $(this).attr('href');
        },
        trigger: 'hover',
        placement: 'bottom',
        selector: 'a'
    });
}

function insertRichTextDeleteControl(elem) {
    var a = $('<a class="icon icon-cross text-replace delete-control">Delete</a>');
    $(elem).addClass('rich-text-deletable').prepend(a);
    a.click(function() {
        var widget = $(elem).parent('.richtext').data('IKS-hallo');
        $(elem).fadeOut(function() {
            $(elem).remove();
            if (widget != undefined && widget.options.editable) {
                widget.element.trigger('change');
            }
        });
    });
}

$(function() {
    $('.richtext [contenteditable="false"]').each(function() {
        insertRichTextDeleteControl(this);
    });
})
