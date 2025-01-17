


import datetime
from microgrid.environments.industrial.industrial_env import IndustrialEnv
from microgrid.agents.internal.check_feasibility import check_industrial_site_feasibility
import numpy as np
from pulp import *
T=48
ind = [i for i in range(T)]
ind1 = [i for i in range(T+1)]

rd,rc = 0.95,0.95
class IndustrialAgent:
    def __init__(self, env: IndustrialEnv):
        self.env = env
        self.nbr_future_time_slots = env.nb_pdt
        self.delta_t = env.delta_t
        self.battery_capacity = env.battery.capacity
        self.battery_pmax = env.battery.pmax
        self.battery_efficiency = env.battery.efficiency

    def take_decision(self,
                      now: datetime.datetime,            # current datetime
                      manager_signal: np.ndarray,        # in R^nbr_future_time_slots
                      soc: float,                        # in [0, battery_capacity]
                      consumption_forecast: np.ndarray   # in R+^nbr_future_time_slots
                      ) -> np.ndarray:                   # in R^nbr_future_time_slots (battery power profile)
        baseline_decision = self.take_my_decision(soc=soc, manager_signal=manager_signal,consumption_forecast=consumption_forecast)
        # use format and feasibility "checker"
        check_msg = self.check_decision(load_profile=baseline_decision)
        # format or infeasiblity pb? Look at the check_msg
        if check_msg['format'] != 'ok' or check_msg['infeas'] != 'ok':
            print(f"Format or infeas. errors: {check_msg}")

        return baseline_decision

    T=48
    rc, rd = 0.95, 0.95
    ind = [i for i in range(T)]
    def take_my_decision(self,
                     soc: float,                 # in [0, battery_capacity]
                          manager_signal: np.ndarray,  # in R^nbr_future_time_slots
                          consumption_forecast) -> np.ndarray:
        bin_var = LpVariable.dicts("bin", ind, cat="Continuous")  # stockage supp d'energie
        bout_var = LpVariable.dicts("bout", ind, cat="Continuous")  # stockage négatif d'energie
        bst_var = LpVariable.dicts("bst", ind1, cat="Continious")  # etat de stockage de la batterie
        g_var = LpVariable.dicts("g", ind, cat="Continuous")

        prob = LpProblem(name="Optimisation_consommation_centrale", sense=LpMinimize)  # On cherche à minimiser
        prob += lpSum([g_var[t]*manager_signal[t] for t in range(T)])

        for t in range(T) :
            prob += bst_var[t + 1] == bst_var[t] + (- (1/rd)*bout_var[t] + rc*bin_var[t])*delta_t/datetime.timedelta(hours = 1)
            prob += g_var[t] + bout_var[t] == consumption_forecast[t] + bin_var[t]
            prob += g_var[t] >= 0

            prob += bst_var[t] >= 0
            prob += bin_var[t] >= 0
            prob += bout_var[t] >= 0
            prob += bst_var[t] <= self.battery_capacity
            prob += bin_var[t] <= self.battery_pmax
            prob += bout_var[t] <= self.battery_pmax

        prob+= bst_var[0]==soc
        prob += bst_var[T] >= 0
        prob+= bst_var[T] <= self.battery_capacity




        prob.solve()
        print("Status:", LpStatus[prob.status])
        baseline_decision = [g_var[t].varValue for t in range(T)]
        soc_decision = [bst_var[t].varValue for t in range(T+1)]
        prob.writeLP("Industrial")
        print((baseline_decision-consumption_forecast).tolist())
        print(soc_decision)

        return np.array(baseline_decision)-consumption_forecast



    def take_baseline_decision(self,
                               soc: float,                 # in [0, battery_capacity]
                               manager_signal: np.ndarray  # in R^nbr_future_time_slots
                               ) -> np.ndarray:
        positive_signal = manager_signal[manager_signal > 0]
        negative_signal = manager_signal[manager_signal < 0]
        # take mean of positive price signal values
        charging_signal = np.mean(positive_signal) if len(positive_signal) > 0 else 0
        # take mean of negative price signal values
        discharging_signal = np.mean(negative_signal) if len(negative_signal) > 0 else 0
        # get current State-of-Charge of battery
        current_soc = soc
        # and apply a "threshold" strategy based on these values, also ensuring physical constraints of the battery
        baseline_decision = np.zeros(self.nbr_future_time_slots)
        for t in range(self.nbr_future_time_slots):
            # charge if positive, and low, signal
            if 0 <= manager_signal[t] <= charging_signal:
                current_decision = self.battery_pmax
            # discharge if negative, and low, signal
            elif manager_signal[t] <= discharging_signal:
                current_decision = - self.battery_pmax
            # idle otherwise
            else:
                current_decision = 0
            # ensure compatibility with battery bounds
            if current_decision > 0:  # with battery capacity when charging
                current_decision = min(current_decision,
                                       (self.battery_capacity - current_soc) / self.battery_efficiency)
            if current_decision < 0:  # with battery soc=0 state when discharging
                current_decision = max(current_decision, -current_soc * self.battery_efficiency)
            baseline_decision[t] = current_decision
            # update current value of SOC
            current_soc += baseline_decision[t] * self.delta_t / datetime.timedelta(hours=1)
        return baseline_decision

    def check_decision(self, load_profile) -> dict:
        check_msg, check_score = check_industrial_site_feasibility(industrial_env=self.env, load_profile=load_profile)
        return check_msg


if __name__ == "__main__":
    delta_t = datetime.timedelta(minutes=30)
    time_horizon = datetime.timedelta(days=1)
    N = time_horizon // delta_t
    industrial_config = {
        'battery': {
            'capacity': 100,
            'efficiency': 0.95,
            'pmax': 25,
        },
        'building': {
            'site': 1,
        }
    }
    env = IndustrialEnv(industrial_config=industrial_config, nb_pdt=N)
    agent = IndustrialAgent(env)
    cumulative_reward = 0
    now = datetime.datetime.now()
    state = env.reset(now, delta_t)
    for i in range(N*2):
        action = agent.take_decision(**state)
        state, reward, done, info = env.step(action)
        cumulative_reward += reward
        if done:
            break
        print(f"action: {action}, reward: {reward}, cumulative reward: {cumulative_reward}")
        print("State: {}".format(state))
