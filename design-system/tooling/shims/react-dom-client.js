module.exports = { createRoot: function(){ return window.ReactDOM.createRoot.apply(null, arguments); }, hydrateRoot: function(){ return window.ReactDOM.hydrateRoot.apply(null, arguments); } };
