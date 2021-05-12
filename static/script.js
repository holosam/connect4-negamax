// Can't use undefined variables.
'use strict';

// Constants.
var slot_pixels = 60;

// Game state variables.
var game_id = "0",
    num_rows = 0,
    num_columns = 0,
    active_game = false;

// Send a request for a new game. Happens on "New Game" button click.
function newGame() {
  var req = new XMLHttpRequest();
  req.onreadystatechange = function() {
    if (req.readyState == 4 && req.status == 200) {
      var resp = JSON.parse(req.responseText);

      // Set the game state variables sent from the server.
      game_id = resp['GameId'];
      num_rows = resp['NumRows'];
      num_columns = resp['NumColumns'];
      active_game = true;

      renderBoard(resp);
    }
  };

  // If the New Game button is pressed during an active game, the server still
  // needs the current game_id to delete it from the db.
  var formatted_params = '';
  if (game_id != '0' && active_game) {
    formatted_params = '?game_id' + escape(game_id);
  }
  req.open('GET', '/newgame' + formatted_params, true);
  req.send();
}

// Send a request to place a piece in the board. Happens when the user clicks
// somewhere on the canvas.
function makeMove(col_index) {
  var req = new XMLHttpRequest();
  req.onreadystatechange = function() {
    if (req.readyState == 4 && req.status == 200) {
      var resp = JSON.parse(req.responseText);
      active_game = !resp['GameOver'];
      renderBoard(resp);
    }
  };

  // The server needs to know which game to increment and which column to move in.
  var formatted_params = '?game_id=' + escape(game_id) + '&column_index=' + col_index;
  req.open('GET', '/makemove' + formatted_params, true);
  req.send();

  // Switch the prompt immediately while waiting for the response.
  document.getElementById("prompt").innerHTML = "Player move in column " + (col_index + 1) + ". Computer thinking...";
}

// Draw the game board in the canvas.
function renderBoard(resp) {
  document.getElementById("prompt").innerHTML = resp["Prompt"];

  var canvas = document.getElementById("gameBoard");
  canvas.width = num_columns * slot_pixels;
  canvas.height = num_rows * slot_pixels;

  // Use the 2D grid context to draw colored circles on the board.
  var context = canvas.getContext("2d");
  for (var row_index = 0; row_index < num_rows; row_index++) {
    for (var col_index = 0; col_index < num_columns; col_index++) {
      context.beginPath();
      // arc(xCoordinate, yCoordinate, radius, start angle, end angle)
      // The center of the circle is half of the slot_pixels size, adjusted by
      // which row and col index we're in. Draw the circles with a slightly
      // smaller radius than half the slot size so they aren't touching.
      context.arc((slot_pixels / 2) + (col_index * slot_pixels),
                  (slot_pixels / 2) + (row_index * slot_pixels),
                  (slot_pixels / 2) - 2, 0, 2 * Math.PI);
      switch(resp['Board'][(num_columns * row_index) + col_index]) {
        case 'X':
          context.fillStyle = '#f06666'; // Red
          break;
        case 'O':
          context.fillStyle = '#6686f0'; // Blue
          break;
        default:
          context.fillStyle = '#DCDCDC'; // Grey
      }
      context.fill();
    }
  }
}

// Debugging Tip: use ctrl+shift+R to hard refresh chrome so it doesn't use
// the cached version of the javascript.
window.addEventListener('load', function () {
  console.log("Loaded!");

  // Must add event listeners after the page is loaded.
  document.getElementById("newGameButton").addEventListener("click", newGame);
  document.getElementById("gameBoard").addEventListener("click", function(event) {
    // Disable dropping pieces while there isn't a game going on.
    if (!active_game) {
      return;
    }

    // Determine which column is clicked by using the coordinate of the click.
    var canvas = document.getElementById("gameBoard");
    var col_index = Math.floor((event.pageX - canvas.offsetLeft) / slot_pixels);
    makeMove(col_index);
  });
});
