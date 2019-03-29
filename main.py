# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import logging
import os

from flask import Flask, render_template, request, Response
from flask_socketio import SocketIO, emit
import sqlalchemy
from scipy.spatial import distance

# Remember - storing secrets in plaintext is potentially unsafe. Consider using
# something like https://cloud.google.com/kms/ to help keep secrets secret.
db_user = os.environ.get("DB_USER")
db_pass = os.environ.get("DB_PASS")
db_name = os.environ.get("DB_NAME")
cloud_sql_connection_name = os.environ.get("CLOUD_SQL_CONNECTION_NAME")

app = Flask(__name__)

async_mode = None
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode=async_mode)

logger = logging.getLogger()

# [START cloud_sql_mysql_sqlalchemy_create]
# The SQLAlchemy engine will help manage interactions, including automatically
# managing a pool of connections to your database
db = sqlalchemy.create_engine(
    # Equivalent URL:
    # mysql+pymysql://<db_user>:<db_pass>@/<db_name>?unix_socket=/cloudsql/<cloud_sql_instance_name>
    sqlalchemy.engine.url.URL(
        drivername='mysql+pymysql',
        username=db_user,
        password=db_pass,
        database=db_name,
        query={
            'unix_socket': '/cloudsql/{}'.format(cloud_sql_connection_name)
        }
    ),
    # ... Specify additional properties here.
    # [START_EXCLUDE]

    # [START cloud_sql_mysql_sqlalchemy_limit]
    # Pool size is the maximum number of permanent connections to keep.
    pool_size=5,
    # Temporarily exceeds the set pool_size if no connections are available.
    max_overflow=2,
    # The total number of concurrent connections for your application will be
    # a total of pool_size and max_overflow.
    # [END cloud_sql_mysql_sqlalchemy_limit]

    # [START cloud_sql_mysql_sqlalchemy_backoff]
    # SQLAlchemy automatically uses delays between failed connection attempts,
    # but provides no arguments for configuration.
    # [END cloud_sql_mysql_sqlalchemy_backoff]

    # [START cloud_sql_mysql_sqlalchemy_timeout]
    # 'pool_timeout' is the maximum number of seconds to wait when retrieving a
    # new connection from the pool. After the specified amount of time, an
    # exception will be thrown.
    pool_timeout=30,  # 30 seconds
    # [END cloud_sql_mysql_sqlalchemy_timeout]

    # [START cloud_sql_mysql_sqlalchemy_lifetime]
    # 'pool_recycle' is the maximum number of seconds a connection can persist.
    # Connections that live longer than the specified amount of time will be
    # reestablished
    pool_recycle=1800,  # 30 minutes
    # [END cloud_sql_mysql_sqlalchemy_lifetime]

    # [END_EXCLUDE]
)
# [END cloud_sql_mysql_sqlalchemy_create]

### 
#@app.before_first_request
#def create_tables():
#    # Create tables (if they don't already exist)
#    with db.connect() as conn:
#        conn.execute(
#            "CREATE TABLE IF NOT EXISTS votes "
#            "( vote_id SERIAL NOT NULL, time_cast timestamp NOT NULL, "
#            "candidate CHAR(6) NOT NULL, PRIMARY KEY (vote_id) );"
#        )
        
@app.route('/', methods=['GET'])
def index():
    votes = []
    with db.connect() as conn:
        # Execute the query and fetch all results
        recent_votes = conn.execute(
            "SELECT candidate, time_cast FROM votes "
            "ORDER BY time_cast DESC LIMIT 5"
        ).fetchall()
        # Convert the results into a list of dicts representing votes
        for row in recent_votes:
            votes.append({
                'candidate': row[0],
                'time_cast': row[1]
            })

        stmt = sqlalchemy.text(
            "SELECT COUNT(vote_id) FROM votes WHERE candidate=:candidate")
        # Count number of votes for tabs
        tab_result = conn.execute(stmt, candidate="TABS").fetchone()
        tab_count = tab_result[0]
        # Count number of votes for spaces
        space_result = conn.execute(stmt, candidate="SPACES").fetchone()
        space_count = space_result[0]

    return render_template(
        'index.html',
        recent_votes=votes,
        tab_count=tab_count,
        space_count=space_count
    )


@app.route('/', methods=['POST'])
def save_vote():
    # Get the team and time the vote was cast.
    team = request.form['team']
    time_cast = datetime.datetime.utcnow()
    # Verify that the team is one of the allowed options
    if team != "TABS" and team != "SPACES":
        logger.warning(team)
        return Response(
            response="Invalid team specified.",
            status=400
        )

    # [START cloud_sql_mysql_sqlalchemy_connection]
    # Preparing a statement before hand can help protect against injections.
    stmt = sqlalchemy.text(
        "INSERT INTO votes (time_cast, candidate)"
        " VALUES (:time_cast, :candidate)"
    )
    try:
        # Using a with statement ensures that the connection is always released
        # back into the pool at the end of statement (even if an error occurs)
        with db.connect() as conn:
            conn.execute(stmt, time_cast=time_cast, candidate=team)
    except Exception as e:
        # If something goes wrong, handle the error in this section. This might
        # involve retrying or adjusting parameters depending on the situation.
        # [START_EXCLUDE]
        logger.exception(e)
        return Response(
            status=500,
            response="Unable to successfully cast vote! Please check the "
                     "application logs for more details."
        )
        # [END_EXCLUDE]
    # [END cloud_sql_mysql_sqlalchemy_connection]

    return Response(
        status=200,
        response="Vote successfully cast for '{}' at time {}!".format(
            team, time_cast)
    )

@app.route('/search2', methods=['POST'])
def search2():
    if not request.json or not 'mode' in request.json:
        return Response(status=400)
    mode = request.form['mode']
    face_identity = request.form['keyword']
    stmt = sqlalchemy.text(
                "SELECT CONVERT(TimeDetect, char) FROM CameraLogs "
                "WHERE FaceID=(:face_id) ORDER BY TimeDetect ASC; "
            )
    try:
        with db.connect() as conn:
            time_detect = conn.execute(stmt, face_id=face_identity )
            arr = []
            for i in time_detect:
                arr.append(i[0])
            emit('my_response', {'time_detect': str(arr)} )
    except Exception as e:
        logger.exception(e)
        return Response(status=500)
    return Response(status=200)

@app.route('/graph')
def dashboard():
    with db.connect() as conn:
        # Execute the query and fetch all results
        recent_logs = conn.execute(
            "SELECT (UNIX_TIMESTAMP(TimeDetect) - MOD(UNIX_TIMESTAMP(TimeDetect), 60))*1000 as MinuteTimestamp, "
            "       COUNT(DISTINCT FaceID) as NumberPeople "
            "FROM CameraLogs "
            "WHERE CameraID='CCTV01' "
            "GROUP BY MinuteTimestamp "
            "ORDER BY MinuteTimestamp ASC; "
        ).fetchall()
        # Convert the results into a list of dicts representing votes
        EachTimestamp = []
        NumberPeople = []
        for row in recent_logs:
            EachTimestamp.append(row[0])
            NumberPeople.append(row[1])
    return render_template(
        'main.html',
        NumberPeople =NumberPeople,
        EachTimestamp = EachTimestamp
    )

@app.route('/live')
def live():
    return render_template('live.html', async_mode=socketio.async_mode)

@app.route('/search')
def search():
    return render_template('search.html',  async_mode=socketio.async_mode)

@socketio.on('my_event', namespace='/search')
def test_message(message):
    if isID(message['keyword']):
        face_identity = message['keyword']

        stmt = sqlalchemy.text(
                    "SELECT UNIX_TIMESTAMP(TimeDetect), FaceImage FROM CameraLogs "
                    "WHERE FaceID IN ( SELECT FaceID FROM FaceIdentityStore "
                                        "WHERE IdentificationNumber=(:face_id) "
                                        "OR StudentIDNumber=(:face_id) "
                                        "OR FaceID=(:face_id) ) "
                    "ORDER BY TimeDetect ASC; "
                )
        try:
            with db.connect() as conn:
                results = conn.execute(stmt, face_id=face_identity )
                time_detect = []
                face_image = []
                for val in results:
                    time_detect.append(val[0])
                    face_image.append(val[1])
                emit('my_response', {'time_detect': time_detect, 'face_image': face_image} )
        except Exception as e:
            logger.exception(e)
def isID(keyword):
    return True 

@app.route('/add_camera_logs', methods=['POST'])
def addCameraLogs():
    return_data = []
    logging.error("addCameraLogs")
    if not request.json or not 'logs' in request.json:
        return Response(
                status=400,
                response="not have json object or logs values in json"
            )
    logs = request.json["logs"]

    face_vector, face_id = get_face_vector_from_cloud_sql()

    face_id_array = []
    camera_id = ''
    time_detect=''
    distance_all = []
    distance_each_all = []
    face_image = []
    
    for idx, log in enumerate(logs):
        #cameraLogs.append([ log['camera_id'], log['face_vector'], log['time_detect'] ])
        camera_id = log['camera_id']
        time_detect = log['time_detect']
        face_image.append( log['face_image'] )
        
        #check face vector from device is same identity from database
        #if not same, add new identity to SQL table FaceIdentityStore
        threshold = 0.75
        minimal_distance = threshold
        distance_each = []
        face_identity = False
        for face_index, vector_each in enumerate(face_vector):
            if len([float(i) for i in vector_each[1:-1].split(",")]) != len([float(i) for i in log['face_vector'][1:-1].split(",")]):
                return Response(
                    status=401,
                    response="length of face vector not match at FaceID : "+str(face_id[face_index])
                        )
            #distance_cal =  distance.euclidean(vector_each, log['face_vector'])
            distance_cal =  distance.euclidean([float(i) for i in vector_each[1:-1].split(",")], [float(i) for i in log['face_vector'][1:-1].split(",")])
            distance_each.append(distance_cal)
            if distance_cal < minimal_distance:
                minimal_distance = distance_cal
                face_identity = face_id[face_index]
        distance_all.append(minimal_distance)
        distance_each_all.append(distance_each)
        if minimal_distance == threshold:
            # INSERT NEW IDENTITY if NOT FIND MINIMAL Distance
            face_identity = len(face_id)+1+idx
            stmt = sqlalchemy.text(
                "INSERT FaceIdentityStore(FaceID, FaceVector, FaceImage)"
                " VALUES (:face_id, :face_vector, :face_image); "
            )
            try:
                with db.connect() as conn:
                    conn.execute(stmt, 
                                face_id=int(face_identity), 
                                face_vector=str(log['face_vector']),
                                face_image=log['face_image'] )
            except Exception as e:
                logger.exception(e)
                return Response(
                    status=500,
                    response="unsuccessful INSERT new Identity to cloud SQL"
                        )
        if face_identity:
            face_id_array.append(face_identity)           
        #INSERT LOGS TO CLOUD SQL
        stmt = sqlalchemy.text(
            "INSERT CameraLogs(CameraID, FaceID, TimeDetect, FaceImage)"
            " VALUES (:camera_id, :face_identity, :time_detect, :face_image)"
        )
        try:
            with db.connect() as conn:
                conn.execute(stmt, 
                             camera_id=camera_id, 
                             face_identity=int(face_identity), 
                             time_detect=time_detect,
                             face_image=log['face_image'])
        except Exception as e:
            logger.exception(e)
            return Response(
                status=500,
                response="unsuccessful INSERT logs from device to cloud SQL"
            )
    print(distance_all)
    distance_each_all
    try:
        live_data = {
                  "camera_id" : camera_id,  # String 
                  "face_id": face_id_array, # Array
                  "time_detect": time_detect,
                  "face_image" : face_image 
                }
        emit('my_response',
            live_data,namespace='/live_camera', broadcast=True)
    except Exception as e:
        logger.exception(e)
        return Response(
            status=500,
            response="Emit broadcast error"
        )
    
    return_data.append({'distance_all':distance_all})
    return_data.append({'distance_each_all':distance_each_all})
    return_data.append({'live_data':live_data})
    return  Response(
            response=str(return_data),
            status=201
        )

def get_face_vector_from_cloud_sql():
    face_vector = []
    face_id = []
    with db.connect() as conn:
        query_all_rows = conn.execute(
            "SELECT FaceVector, FaceID FROM FaceIdentityStore; "
        ).fetchall()

        for row in query_all_rows:
            face_vector.append(row[0])
            face_id.append(row[1])

    return face_vector, face_id


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
