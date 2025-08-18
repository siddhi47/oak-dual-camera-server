PISN=$(tr -d '\0' </sys/firmware/devicetree/base/serial-number)
SUBSN=$(echo $PISN | awk '{print substr($1, 9, 8)}')
DEVICE_NAME="gtjet$SUBSN"

export PISN=$PISN
export DEVICE_NAME=$DEVICE_NAME
export DEVICE_SERIAL=$DEVICE_NAME
PASSWORD=$(echo -n $DEVICE_NAME | sha256sum | awk '{print substr($1, 0, 15)}')
export DEVICE_PASSWORD=$PASSWORD

# Get the current hour in 24-hour format
current_hour=$(date +%H)

# Check if the current hour is between 20 (8 PM) and 4 (4 AM)
if [ "$current_hour" -ge 20 ] || [ "$current_hour" -lt 4 ]; then
  # Run your script here
  echo "It's between 8 PM and 4 AM. Running your script..."
  # Replace the following line with the command to run your script
  python3 s3uploader.py --user $DEVICE_SERIAL --password $DEVICE_PASSWORD
  sleep 3600
else
  echo "It's not between 8 PM and 4 AM. Script will not be executed."
  sleep 3600
fi
