from flask import Flask, jsonify, render_template, request
from google.cloud import datastore
from random import randint

app = Flask(__name__)
db = datastore.Client()

# Note: If these fields are changed and rows*columns becomes an odd number,
# the tie game checking will break because it only checks on even moves.
STANDARD_ROWS = 6
STANDARD_COLUMNS = 7
STANDARD_NUM_TO_WIN = 4
DEFAULT_DIFFICULTY = 5
INF = float("inf")

# Server-side representation of the game pieces.
PIECE_EMPTY = "*"
GAME_PIECES = ["X", "O"]

# Filenames.
HTML_TEMPLATE = "index.html"

# HTTP Request Parameters.
ID_PARAM = "game_id"
COLUMN_PARAM = "column_index"

# Datastore table names.
GAME_STATE_TABLE = "GameState"
GAME_WINS_TABLE = "GameWins"

# JSON field names.
GAME_ID_FIELD = "GameId"
NUM_ROWS_FIELD = "NumRows"
NUM_COLUMNS_FIELD = "NumColumns"
NUM_TO_WIN_FIELD = "NumToWin"
MOVES_MADE_FIELD = "MovesMade"
BOARD_FIELD = "Board"
GAME_OVER_FIELD = "GameOver"
PROMPT_FIELD = "Prompt"
HUMAN_WINS_FIELD = "HumanWins"
COMP_WINS_FIELD = "ComputerWins"
TIES_FIELD = "Ties"


class Game:
    # Initialize the game from a datastore Entity for the game state, which
    # holds the size of the board and the moves made up until this point.
    def __init__(self, game_state):
        self.num_rows = game_state[NUM_ROWS_FIELD]
        self.num_columns = game_state[NUM_COLUMNS_FIELD]
        self.num_to_win =  game_state[NUM_TO_WIN_FIELD]
        self.game_piece_index = 0  # Flips between 0 and 1 in __new_turn().

        # Can reference a spot with self.board[row_index][column_index]
        self.board = [[PIECE_EMPTY] * self.num_columns for _ in range(self.num_rows)]
        # Hold a list of the next available row_index for each column as a
        # shortcut for inserting new game pieces.
        self.open_rows = [self.num_rows - 1] * self.num_columns
        # Holds a list of column_indexes to track the moves made, which is used
        # to recover a saved Game and in undo_last_move().
        self.moves_made = []

        # Holds the output of __negamax_eval() of the current game state.
        self.negamax_score = 0

        # Catch this game state up to the moves that have been made.
        for column_index in game_state[MOVES_MADE_FIELD]:
            self.make_move(column_index)

    def get_num_columns(self):
        return self.num_columns

    def get_moves_made(self):
        return self.moves_made

    def get_negamax_score(self):
        return self.negamax_score

    # Create a 1D representation of the board to send to the client for display.
    def get_flat_board(self):
        flat_board = []
        for row in self.board:
            for spot in row:
                flat_board.append(spot)
        return flat_board

    # Returns true if this column is a valid index and not full.
    def can_make_move(self, column_index):
        return column_index >= 0 and column_index < self.num_columns and self.open_rows[column_index] >= 0

    # Drops a piece in the specified column. Returns True if the game is over.
    # Throws an exception in the column is full. 
    def make_move(self, column_index):
        if not self.can_make_move(column_index):
            raise AssertionError("Can't move in full column " + str(column_index))

        # Drop the piece into the proper slot.
        self.board[self.open_rows[column_index]][column_index] = GAME_PIECES[self.game_piece_index]

        # Update game state variables.
        self.moves_made.append(column_index)
        self.open_rows[column_index] -= 1
        self.__new_turn()

        # Get a negamax evaluation for this game state.
        negamax_score, is_game_over = self.__negamax_eval()
        self.negamax_score = negamax_score
        return is_game_over

    # Undoes the most recent move. Used in game simulations to avoid cloning
    # the game state.
    def undo_last_move(self):
        # Get the column_index and the row_index for the last made move.
        column_index = self.moves_made.pop()
        self.open_rows[column_index] += 1

        # Because of the line above, self.open_rows[column_index] references
        # the highest position in this column with a piece.
        self.board[self.open_rows[column_index]][column_index] = PIECE_EMPTY

        # Flip the turn back to the previous player.
        self.__new_turn()

    def __new_turn(self):
        self.game_piece_index = 1 - self.game_piece_index

    # Negamax scoring is a method of evaluating the board in a zero-sum way. So
    # the score for the X piece will be -1 * the score for the O piece.
    def __negamax_eval(self):
        # Indexed by line_counts[piece_count][game_piece_index]. Each element
        # holds the number of lines on the board that contain that many pieces
        # for that particular game_piece.
        line_counts = [[0] * 2 for _ in range(self.num_to_win + 1)]

        # Search through every possible num_to_win line of pieces.
        for row_index in range(self.num_rows):
            for column_index in range(self.num_columns):
                line_counts = self.__count_pieces_in_line(line_counts, row_index, column_index, self.__go_right)
                line_counts = self.__count_pieces_in_line(line_counts, row_index, column_index, self.__go_down)
                line_counts = self.__count_pieces_in_line(line_counts, row_index, column_index, self.__go_down_right)
                line_counts = self.__count_pieces_in_line(line_counts, row_index, column_index, self.__go_up_right)

        # Add to the negamax_score if there are lines made of only one piece
        # and empties.
        negamax_score = 0
        for piece_count, line_count_list in enumerate(line_counts):
            # Strongly prefer more pieces in a row, so use piece_count^4.
            negamax_score += line_count_list[self.game_piece_index] * (piece_count ** 4)
            negamax_score -= line_count_list[1 - self.game_piece_index] * (piece_count ** 4)

        # Check if the game is over this turn by seeing if the opposing piece
        # has a line of num_to_win in a row. This function is called after
        # __new_turn(), so the last move was made by the opposing piece.
        return negamax_score, line_counts[self.num_to_win][1 - self.game_piece_index] >= 1
    
    # Searches along a line of pieces for lines that have only one player's
    # game piece or empties. If this is the case, it adds 1 to the proper index
    # in line_counts.
    def __count_pieces_in_line(self, line_counts, row_index, column_index, direction_function):
        current_piece_count = 0
        opposing_piece_count = 0

        # First check if the end of the line will run outside of the board to
        # avoid unnecessary iterations.
        last_row_index, last_column_index = direction_function(row_index, column_index, self.num_to_win - 1)
        if last_row_index < 0 or last_row_index >= self.num_rows or last_column_index < 0 or last_column_index >= self.num_columns:
            # This is an invalid line, so nothing can be added to line_counts.
            return line_counts

        # Search along the line and increment the piece_count values.
        for piece_index in range(self.num_to_win):
            found_row_index, found_column_index = direction_function(row_index, column_index, piece_index)
            found_piece = self.board[found_row_index][found_column_index]

            if found_piece == GAME_PIECES[self.game_piece_index]:
                current_piece_count += 1
            elif found_piece == GAME_PIECES[1 - self.game_piece_index]:
                opposing_piece_count += 1

        # If the line is purely made of the currently active piece, add it to
        # line_counts.
        if current_piece_count >= 1 and opposing_piece_count == 0:
            line_counts[current_piece_count][self.game_piece_index] += 1
        elif opposing_piece_count >= 1 and current_piece_count == 0:
            line_counts[opposing_piece_count][1 - self.game_piece_index] += 1

        return line_counts

    # Helpers to navigate in one direction on the board.
    def __go_right(self, row_index, column_index, piece_index):
        return row_index, column_index + piece_index

    def __go_down(self, row_index, column_index, piece_index):
        return row_index + piece_index, column_index

    def __go_down_right(self, row_index, column_index, piece_index):
        return row_index + piece_index, column_index + piece_index

    def __go_up_right(self, row_index, column_index, piece_index):
        return row_index - piece_index, column_index + piece_index


# Does a Minimax search down all possible game moves from this point, using
# Negamax scoring of the game to decide which move is the best to make.
# Uses alpha beta pruning to decrease the number of nodes that have to be
# evaluated.
def negamax_move(game, depth, alpha=-INF, beta=INF):
    move_to_make = -1

    # The deepest game states provide the scores that get bubbled up.
    if depth == 0:
        return game.get_negamax_score(), move_to_make

    # Start with the lowest possible score.
    best_score = -INF

    # Iterate through all possible moves from this point.
    for column_index in range(game.get_num_columns()):
        if not game.can_make_move(column_index):
            continue

        if game.make_move(column_index):
            # If this move ends the game, this is a desirable state so max out
            # best_score. Give a slightly higher score to more imminent wins.
            best_score = 1000 + depth
            move_to_make = column_index
        else:
            # Search through subsequent game states to find their scores.
            # Since this is a Negamax score, the opponents scores are the
            # exact opposite so the alpha beta window is flipped each turn.
            negamax_score, _ = negamax_move(game, depth - 1, -beta, -alpha)
            negamax_score = -negamax_score

            # This game state results in a better score, so save it.
            if negamax_score > best_score:
                best_score = negamax_score
                move_to_make = column_index

        # The game state has been evaluated, so revert the move.
        game.undo_last_move()

        alpha = max(alpha, best_score)
        if alpha >= beta:
            # The alpha beta window has closed so no other states need to
            # be evaluated.
            break

    return best_score, move_to_make


def game_state_key(game_id):
    return db.key(GAME_STATE_TABLE, game_id)


# Edits the number of wins per player in the db. Sets the response prompt to
# report the overall score to the player.
def increment_wins(winner_field, response):
    wins_key = db.key(GAME_WINS_TABLE, GAME_WINS_TABLE)
    wins_entity = db.get(wins_key)

    # Could not find the wins_entity, so create it. Should only happen once.
    if wins_entity is None:
        wins_entity = datastore.Entity(key=wins_key)
        wins_entity[HUMAN_WINS_FIELD] = 0
        wins_entity[COMP_WINS_FIELD] = 0
        wins_entity[TIES_FIELD] = 0

    wins_entity[winner_field] += 1

    prompt = ""
    if winner_field == HUMAN_WINS_FIELD:
        prompt = "Human Wins!"
    elif winner_field == COMP_WINS_FIELD:
        prompt = "Computer Wins!"
    else:
        prompt = "It's a tie!"

    # Upsert the new score.
    db.put(wins_entity)

    # Edit the response fields for the game being over.
    prompt += " Total score is Humans: " + str(wins_entity[HUMAN_WINS_FIELD]) + ", Computer: " + str(wins_entity[COMP_WINS_FIELD]) + ", Ties: " + str(wins_entity[TIES_FIELD])
    response[GAME_OVER_FIELD] = True
    response[PROMPT_FIELD] = prompt
    return response


@app.route("/")
def root():
    return render_template(HTML_TEMPLATE)


@app.route("/newgame")
def new_game():
    # A game_id is sent when the user ended a game early, so it needs to be
    # removed from the db since it will never finish.
    last_game_id = request.args.get(ID_PARAM)
    if last_game_id is not None:
        db.delete(game_state_key(last_game_id))

    # Create a random ID to represent this game, so multiple games can be
    # played at the same time, with a very small chance of colliding. I am
    # deliberately making it so a finite number of games can exist, because 
    # there's a scenario where the user could refresh the page in the middle of
    # a game and the game_state never gets deleted from the db, so this allows
    # orphaned games to (eventually) be overwritten.
    game_id = str(randint(1, 10000000))

    # Create a dictionary to hold the information that will be passed back to
    # the client via JSON.
    response = {}
    response[GAME_ID_FIELD] = game_id
    response[GAME_OVER_FIELD] = False
    response[PROMPT_FIELD] = "Click on the board to make a move. You go first."

    # Insert a new game_state into the db.
    with db.transaction():
        game_state = datastore.Entity(key=game_state_key(game_id))
        game_state[NUM_ROWS_FIELD] = STANDARD_ROWS
        game_state[NUM_COLUMNS_FIELD] = STANDARD_COLUMNS
        game_state[NUM_TO_WIN_FIELD] = STANDARD_NUM_TO_WIN
        game_state[MOVES_MADE_FIELD] = []

        db.put(game_state)

        # Fill the response fields needed for displaying the game.
        response[NUM_ROWS_FIELD] = game_state[NUM_ROWS_FIELD]
        response[NUM_COLUMNS_FIELD] = game_state[NUM_COLUMNS_FIELD]
        game = Game(game_state)
        response[BOARD_FIELD] = game.get_flat_board()
    return jsonify(response)


@app.route("/makemove")
def make_move():
    # Get the request params for which game to get and which move to make.
    game_id_param = request.args.get(ID_PARAM)
    human_move_param = request.args.get(COLUMN_PARAM)

    # This will only happen if a malformed request is sent perhaps by manual
    # input, so okay to return an error on this.
    if game_id_param is None or human_move_param is None:
        raise AssertionError("Invalid request.")

    response = {}
    response[GAME_OVER_FIELD] = False

    with db.transaction():
        game_key = game_state_key(game_id_param)
        game_state = db.get(game_key)
        if game_state is None:
            raise AssertionError("Nonexistent game_id.")

        game = Game(game_state)

        # Will throw an exception if it's not an int.
        human_move = int(human_move_param)
        if not game.can_make_move(human_move):
            response[PROMPT_FIELD] = "Can't move in column " + str(human_move + 1)
            response[BOARD_FIELD] = game.get_flat_board()
            return jsonify(response)

        if game.make_move(human_move):
            # This game_state is no longer needed. Delete it and return early.
            db.delete(game_key)
            response[BOARD_FIELD] = game.get_flat_board()
            return jsonify(increment_wins(HUMAN_WINS_FIELD, response))

        _, cpu_move = negamax_move(game, DEFAULT_DIFFICULTY)
        if game.make_move(cpu_move):
            db.delete(game_key)
            response[BOARD_FIELD] = game.get_flat_board()
            return jsonify(increment_wins(COMP_WINS_FIELD, response))

        # Since the human player always goes first and a tie game happens on
        # an even number of moves (42 in the standard game, see note at the top)
        # then this only needs to be checked after an even move is made.
        tie_game = True
        for column_index in range(game.get_num_columns()):
            if game.can_make_move(column_index):
                tie_game = False
                break
        if tie_game:
            db.delete(game_key)
            response[BOARD_FIELD] = game.get_flat_board()
            return jsonify(increment_wins(TIES_FIELD, response))

        # Update the game_state in the db with new moves.
        game_state[MOVES_MADE_FIELD] = game.get_moves_made()
        db.put(game_state)

        # Prompt the player to make another move.
        response[PROMPT_FIELD] = "Computer moves in column " + str(cpu_move + 1) + ". Your turn."
        response[BOARD_FIELD] = game.get_flat_board()

    return jsonify(response)


if __name__ == "__main__":
    app.run(debug=True)
    # To run locally: app.run(host="127.0.0.1", port=8080, debug=True)
