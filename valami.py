import netsquid as ns
from components.protocols.clock import Clock

# Define a simple function to be triggered by the clock
clock = Clock(delta_time=5)
clock.start()

# Run the simulation for 25 time units
ns.sim_run(26)

# Get the current simulation time after running the simulation
current_time = ns.sim_time()
print(f"Simulation ended at time {current_time}")