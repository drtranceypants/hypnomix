// `print` for Node.js, loaded with --require by tests/_jscheck.runner(): macOS's JavaScript engine has it, and the scripts the
// tests run (a Max device script, a page script against stand-ins) use it to hand their answer back.
globalThis.print = function () { console.log(Array.prototype.slice.call(arguments).join(' ')); };
