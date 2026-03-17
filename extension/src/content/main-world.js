// メインワールドで実行されるスクリプト
// React Fiberツリーを辿ってDownshiftから求人を選択する

document.addEventListener('__scout_click_option', function(e) {
  var detail = e.detail;
  var index = detail.index;

  // 1. option要素のFiberからアイテムデータを取得
  var options = document.querySelectorAll('[role="option"]');
  var targetOption = options[index];
  if (!targetOption) {
    console.log('[Scout Assistant MW] option[' + index + '] not found');
    return;
  }

  // option要素のFiberを取得
  var optFiberKey = Object.keys(targetOption).find(function(k) {
    return k.startsWith('__reactInternalInstance$') || k.startsWith('__reactFiber$');
  });
  if (!optFiberKey) {
    console.log('[Scout Assistant MW] No fiber on option element');
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
    return;
  }

  // 3. itemが見つかっていればselectItem
  if (item !== null) {
    console.log('[Scout Assistant MW] Calling selectItem with found item');
    downshift.selectItem(item);
    return;
  }

  // 4. itemが見つからない場合: Downshiftのstate.highlightedIndexを使う
  // highlightedIndexをセットしてからselectHighlightedItem
  console.log('[Scout Assistant MW] item not found in fiber, trying selectItemAtIndex');
  console.log('[Scout Assistant MW] Downshift state:', JSON.stringify({
    highlightedIndex: downshift.state.highlightedIndex,
    isOpen: downshift.state.isOpen,
    selectedItem: downshift.state.selectedItem,
  }));

  // Downshiftの内部メソッドをチェック
  var methods = Object.getOwnPropertyNames(Object.getPrototypeOf(downshift)).filter(function(m) {
    return typeof downshift[m] === 'function';
  });
  console.log('[Scout Assistant MW] Downshift methods:', methods.join(', '));

  // highlightedIndexを設定してselectHighlightedItemを呼ぶ
  if (typeof downshift.selectHighlightedItem === 'function') {
    downshift.internalSetState({ highlightedIndex: index }, function() {
      downshift.selectHighlightedItem();
      console.log('[Scout Assistant MW] Called selectHighlightedItem at index:', index);
    });
  } else {
    // setHighlightedIndex + Enter相当
    downshift.internalSetState({
      type: '__item_click__',
      highlightedIndex: index,
    });
    console.log('[Scout Assistant MW] Set highlightedIndex to', index);
  }
});

console.log('[Scout Assistant MW] Main world script loaded');
