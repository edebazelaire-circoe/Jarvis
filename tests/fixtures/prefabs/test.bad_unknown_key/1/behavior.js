jarvis.on('init', function () {
  document.querySelector('button').addEventListener('click', function () {
    var next = jarvis.data.count + 1;
    jarvis.emit('incremented', { count: next });
  });
});
