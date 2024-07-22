import numpy as np
import matplotlib.pyplot as plt
import os

def generate_angles(dir, peaks, contributions, kappa, num_points):
    """
    This function generates a multimodal von Mises distribution with the given peaks, contributions, and kappa.
    It saves the generated data in radians and degrees to files and plots the distribution in polar and X-Y plots.
    :param peaks: array of mean directions (peaks) in degrees
    :param contributions: array of contributions of each peak (sum should be 1)
    :param kappa: concentration parameter of the von Mises distribution
    :param num_points: number of data points to generate

    :return: the generated angle array
    """
    def von_mises_distribution(peaks, contributions, kappa, num_points):
        data = np.array([])
        for peak, contribution in zip(peaks, contributions):
            if contribution > 0:
                num_points_peak = int(num_points * contribution)
                data_peak = np.random.vonmises(mu=peak, kappa=kappa, size=num_points_peak)
                data = np.concatenate((data, data_peak))
        return data

    # Convert peaks to radians for circular distribution
    peaks_rad = np.deg2rad(peaks)

    # Generate the von Mises multimodal distribution
    data_rad = von_mises_distribution(peaks_rad, contributions, kappa, num_points)

    # Convert data back to degrees for X-Y plotting and ensure all angles are positive
    data_degrees = (np.rad2deg(data_rad) + 360) % 360

    # Save the arrays to files
    np.savetxt(os.path.join(dir, "data_rad.txt"), data_rad, fmt='%f')
    np.savetxt(os.path.join(dir, "data_degrees.txt"), data_degrees, fmt='%f')

    # Plotting the polar plot with reoriented 0 degrees
    fig = plt.figure(figsize=(12, 6))
    ax = fig.add_subplot(121, polar=True)
    ax.hist(data_rad, bins=1000, density=False, alpha=0.5, color='g')
    ax.set_theta_zero_location('S')  # Set 0 degrees to the bottom
    ax.set_title('Multimodal von Mises Distribution (Polar)', va='bottom')

    # Plotting the histogram on X-Y plot
    ax2 = fig.add_subplot(122)
    ax2.hist(data_degrees, bins=1000, density=True, alpha=0.5, color='g')
    ax2.set_title('Multimodal von Mises Distribution (X-Y)')
    ax2.set_xlabel('ET angle (degrees)')
    ax2.set_ylabel('Frequency')

    # Save the plots
    plt.tight_layout()
    plt.savefig(os.path.join(dir, 'von_mises_distribution_plots.png'))
    plt.show()

    # randomize the list
    np.random.shuffle(data_rad)

    return data_rad

