import datetime
import logging
import numpy as np
import base64
from flask import Flask, render_template, request, Response, jsonify, json
from flask_socketio import SocketIO, emit

app = Flask(__name__)

async_mode = None
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode=async_mode)

logger = logging.getLogger()


@app.route('/live')
def live():
    return render_template('live.html', async_mode=socketio.async_mode)

@app.route('/test_add_camera_logs', methods=['POST'])
def testAddCameraLogs():
    if not request.json or not 'logs' in request.json:
        return  Response(
            response="not have logs", status=400)
    logs = request.json["logs"]
    
    face_id_array = 'ABX1'
    camera_id = logs[0]['camera_id']
    time_detect=logs[0]['time_detect']
    face_image = logs[0]['face_image']
    face_image_to_html = "data:image/png;base64,"+str(face_image)[2:-1]

    try:
        #face_image = ['']
        live_data = {
                  "camera_id" : camera_id,  # String 
                  "face_id": face_id_array, # Array
                  "time_detect": time_detect,
                  "face_image" : face_image
                }
        emit('my_response',
            live_data,namespace='/live_camera', broadcast=True)
        print(live_data)
    except Exception as e:
        logger.exception(e)
        return Response(
            status=500,
            response="Emit broadcast error"
        )

    return  Response(
            response=str([{'z':live_data},{'a':live_data}]),
            status=201
        )


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
