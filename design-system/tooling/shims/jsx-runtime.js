var R = window.React;
function jsx(type, props, key) {
  var p = props || {};
  if (key !== undefined) { p = Object.assign({}, p, { key: key }); }
  return R.createElement(type, p);
}
module.exports = { jsx: jsx, jsxs: jsx, jsxDEV: jsx, Fragment: R.Fragment };
