/*\

title: $:/plugins/felixhayashi/hotzone/hotzone.js
type: application/javascript
module-type: startup

@preserve

\*/

(function(){

/*jslint node: true, browser: true */
/*global $tw: false */
"use strict";

// Export name and synchronous status
exports.name = "hotzone";
exports.platforms = ["browser"];
exports.after = ["render"];
exports.synchronous = true;

exports.startup = function() {

var config = require("$:/plugins/felixhayashi/hotzone/config.js").config;

var curRef = null;
var storyRiverElement = document.getElementsByClassName(config.classNames.storyRiver)[0];
var userConf = $tw.wiki.getTiddlerData(config.references.userConfig, {});
var focusOffset = (isNaN(parseInt(userConf.focusOffset))
                   ? 150 : parseInt(userConf.focusOffset));

var extractTitleFromFrame = function(target) {

  if(!(target instanceof Element)) return;
  if(!$tw.utils.hasClass(target, config.classNames.tiddlerFrame)) return;

  // Use data attribute (works for both view and edit/draft frames)
  var dataTitle = target.getAttribute("data-tiddler-title");
  if(dataTitle) return dataTitle;

  // Fallback to tc-title element
  var el = target.getElementsByClassName(config.classNames.tiddlerTitle)[0];
  if(el) {
    var title = el.innerText || el.textContent;
    return title.trim();
  }

};

var focusActionButton = function(target) {
  if(!target) return;
  var isEdit = $tw.utils.hasClass(target, "tc-tiddler-edit-frame");
  if(isEdit) {
    var saveBtn = target.querySelector('button[aria-label="Confirm changes to this tiddler"]');
    if(saveBtn) saveBtn.focus({preventScroll: true});
  } else {
    var closeBtn = target.querySelector('button[aria-label="close"]');
    if(closeBtn) closeBtn.focus({preventScroll: true});
  }
};

var registerFocusChange = function(tRef, target) {

  $tw.wiki.addTiddler(new $tw.Tiddler({
      title: config.references.focussedTiddlerStore,
      text: tRef
    },
    $tw.wiki.getModificationFields()
  ));

  if(target) {
    var prevTarget = document.getElementsByClassName("hzone-focus")[0];
    if(prevTarget) {
      $tw.utils.removeClass(prevTarget, "hzone-focus");
    }
    $tw.utils.addClass(target, "hzone-focus");
    var activeEl = document.activeElement;
    var activeLost = !activeEl || activeEl === document.body;
    if(keyboardNav || activeLost) {
      focusActionButton(target);
    }
  }

};

var keyboardNav = false;
var keyboardNavTimeout = null;

var checkForFocusChange = function() {

  if(keyboardNav) {
    console.log("hotzone: skipping scroll check (keyboard nav active)");
    return;
  }

  var tObj = $tw.wiki.getTiddler("$:/StoryList");
  if(tObj && tObj.fields.list.length) {

    var target = null;
    var minDistance = Number.MAX_VALUE;
    var childElements = storyRiverElement.children;
    var tiddlerFrameClass = config.classNames.tiddlerFrame;
    for(var i = childElements.length; i--;) {
      if($tw.utils.hasClass(childElements[i], tiddlerFrameClass)) {
        var frameElRect = childElements[i].getBoundingClientRect();
        var distance = Math.min(
                         Math.abs(focusOffset - frameElRect.top),
                         Math.abs(focusOffset - frameElRect.bottom)
                      );
        if(distance < minDistance) {
          target = childElements[i];
          minDistance = distance;
        }
      }
    }

    var title = extractTitleFromFrame(target);
    console.log("hotzone: scroll check, closest:", title, "current:", curRef);

    if(title !== curRef && $tw.wiki.getTiddler(title)) {
      curRef = title;
      registerFocusChange(curRef, target);
      return;
    }

  } else if(curRef) {
    curRef = "";
    registerFocusChange(curRef);
  }

};

var debounce = function(func) {
  var timeout;
  var dontStart = false;
  return function(wait, stopOthers) {
    var context = this;

    if (dontStart && !stopOthers) {
      // do nothing
    } else {
      dontStart = stopOthers;

      if (timeout != null) {
        clearTimeout(timeout);
      }

      timeout = setTimeout(function () {
        timeout = null;
        dontStart = false;
        func.apply(context);
      }, wait);
    }
  };
};

var update = debounce(checkForFocusChange);

var handleChangeEvent = function(changedTiddlers) {

  if(changedTiddlers["$:/HistoryList"]) {

    if(!$tw.wiki.tiddlerExists("$:/HistoryList")) return;

    var curTiddler = $tw.wiki.getTiddler("$:/HistoryList").fields["current-tiddler"];
    var storyList = $tw.wiki.getTiddlerList("$:/StoryList");
    var isInStoryList = storyList.indexOf(curTiddler) >= 0;
    if(!isInStoryList) return;

    update($tw.utils.getAnimationDuration() + 10, true);

  } else if(changedTiddlers["$:/StoryList"]) {

    update($tw.utils.getAnimationDuration() + 10, true);

  }

};

var handleScrollEvent = function(event) {
  update(300, false);
};

var getFrames = function() {
  var result = [];
  var children = storyRiverElement.children;
  var cls = config.classNames.tiddlerFrame;
  for(var i = 0; i < children.length; i++) {
    if($tw.utils.hasClass(children[i], cls)) {
      result.push(children[i]);
    }
  }
  return result;
};

var pendingIdx = -1;

var moveFocus = function(direction) {
  var frames = getFrames();
  if(!frames.length) return;

  // Use tracked index if available, otherwise find from DOM
  var idx;
  if(pendingIdx >= 0 && pendingIdx < frames.length) {
    idx = pendingIdx;
  } else {
    var currentFrame = document.getElementsByClassName("hzone-focus")[0];
    idx = currentFrame ? frames.indexOf(currentFrame) : -1;
  }
  var newIdx = idx + direction;

  if(newIdx < 0) newIdx = 0;
  if(newIdx >= frames.length) newIdx = frames.length - 1;
  if(newIdx === idx) return;

  pendingIdx = newIdx;
  var target = frames[newIdx];
  var title = extractTitleFromFrame(target);
  console.log("hotzone: keyboard move", direction > 0 ? "down" : "up", "to:", title);
  if(title) {
    keyboardNav = true;
    curRef = title;
    registerFocusChange(curRef, target);
    var rect = target.getBoundingClientRect();
    window.scrollTo({top: window.scrollY + rect.top - focusOffset, behavior: "smooth"});
    // Suppress scroll-triggered recalculation during smooth scroll
    if(keyboardNavTimeout) clearTimeout(keyboardNavTimeout);
    keyboardNavTimeout = setTimeout(function() {
      keyboardNav = false;
      pendingIdx = -1;
    }, 600);
  }
};

var handleKeyDown = function(event) {
  if(event.repeat) return;
  if(!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if(event.key === "ArrowUp") {
    event.preventDefault();
    moveFocus(-1);
  } else if(event.key === "ArrowDown") {
    event.preventDefault();
    moveFocus(1);
  } else if(event.key === "PageUp") {
    event.preventDefault();
    moveFocus(-Infinity);
  } else if(event.key === "PageDown") {
    event.preventDefault();
    moveFocus(Infinity);
  }
};

$tw.wiki.addEventListener("change", handleChangeEvent);
window.addEventListener("scroll", handleScrollEvent, false);
window.addEventListener("keydown", handleKeyDown, true);

handleScrollEvent();

};

})();
