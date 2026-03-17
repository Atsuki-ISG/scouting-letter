// メインワールドで実行されるスクリプト
// React Fiberツリーを辿ってDownshiftから求人を選択する

function dispatchResult(success, selectedValue, error) {
  window.dispatchEvent(new CustomEvent('__scout_job_offer_result__', {
    detail: { success: success, selectedValue: selectedValue || '', error: error || '' },
  }));
}

document.addEventListener('__scout_click_option', function(e) {
  var detail = e.detail;
  var index = detail.index;

  // 1. option要素のFiberからアイテムデータを取得
  var options = document.querySelectorAll('[role="option"]');
  var targetOption = options[index];
  if (!targetOption) {
    console.log('[Scout Assistant MW] option[' + index + '] not found');
    dispatchResult(false, '', 'option_not_found');
    return;
  }

  // option要素のFiberを取得
  var optFiberKey = Object.keys(targetOption).find(function(k) {
    return k.startsWith('__reactInternalInstance$') || k.startsWith('__reactFiber$');
  });
  if (!optFiberKey) {
    console.log('[Scout Assistant MW] No fiber on option element');
    dispatchResult(false, '', 'no_fiber');
    return;
  }

  // option要素のpropsからitem/onClick/onMouseDownを探す
  var optFiber = targetOption[optFiberKey];
  var item = null;

  // Fiberツリーを上に辿ってitemを見つける
  var f = optFiber;
  for (var i = 0; i < 20 && f; i++) {
    var props = f.memoizedProps;
    if (props) {
      // Downshiftのrender prop内でgetItemPropsが呼ばれた結果のpropsにitemがある場合
      if (props.item !== undefined) {
        item = props.item;
        console.log('[Scout Assistant MW] Found item in fiber props:', JSON.stringify(item).slice(0, 100));
        break;
      }
      // onClickにバインドされたitemを探す（Downshiftが生成するprops）
      if (props['aria-selected'] !== undefined && props.id) {
        console.log('[Scout Assistant MW] Downshift item props found, id:', props.id, 'role:', props.role);
      }
    }
    f = f.return;
  }

  // 2. Downshiftインスタンスを探す
  var combobox = document.querySelector('[role="combobox"]');
  if (!combobox) {
    console.log('[Scout Assistant MW] combobox not found');
    dispatchResult(false, '', 'no_combobox');
    return;
  }
  var cbFiberKey = Object.keys(combobox).find(function(k) {
    return k.startsWith('__reactInternalInstance$') || k.startsWith('__reactFiber$');
  });
  var fiber = combobox[cbFiberKey];
  var downshift = null;
  var current = fiber;
  for (var j = 0; j < 50 && current; j++) {
    if (current.stateNode && typeof current.stateNode.selectItem === 'function') {
      downshift = current.stateNode;
      break;
    }
    current = current.return;
  }

  if (!downshift) {
    console.log('[Scout Assistant MW] Downshift instance not found');
    dispatchResult(false, '', 'no_downshift');
    return;
  }

  // 3. itemが見つかっていればselectItem
  if (item !== null) {
    console.log('[Scout Assistant MW] Calling selectItem with found item');
    downshift.selectItem(item);
    // selectItem後のstateを確認
    setTimeout(function() {
      var selected = downshift.state.selectedItem;
      var selectedStr = selected ? JSON.stringify(selected) : '';
      console.log('[Scout Assistant MW] After selectItem, selectedItem:', selectedStr.slice(0, 100));
      dispatchResult(true, selectedStr);
    }, 100);
    return;
  }

  // 4. itemが見つからない場合: Downshiftのstate.highlightedIndexを使う
  console.log('[Scout Assistant MW] item not found in fiber, trying selectItemAtIndex');
  console.log('[Scout Assistant MW] Downshift state:', JSON.stringify({
    highlightedIndex: downshift.state.highlightedIndex,
    isOpen: downshift.state.isOpen,
    selectedItem: downshift.state.selectedItem,
  }));

  // highlightedIndexを設定してselectHighlightedItemを呼ぶ
  if (typeof downshift.selectHighlightedItem === 'function') {
    downshift.internalSetState({ highlightedIndex: index }, function() {
      downshift.selectHighlightedItem();
      console.log('[Scout Assistant MW] Called selectHighlightedItem at index:', index);
      setTimeout(function() {
        var selected = downshift.state.selectedItem;
        var selectedStr = selected ? JSON.stringify(selected) : '';
        dispatchResult(true, selectedStr);
      }, 100);
    });
  } else {
    // setHighlightedIndex + Enter相当
    downshift.internalSetState({
      type: '__item_click__',
      highlightedIndex: index,
    });
    console.log('[Scout Assistant MW] Set highlightedIndex to', index);
    setTimeout(function() {
      var selected = downshift.state.selectedItem;
      var selectedStr = selected ? JSON.stringify(selected) : '';
      dispatchResult(!!selected, selectedStr, selected ? '' : 'no_selected_item');
    }, 100);
  }
});

console.log('[Scout Assistant MW] Main world script loaded');
